#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <math.h>

// ===================== WiFi配置 =====================
#define WIFI_NAME       "CirkitWifi"
#define WIFI_PASSWORD   ""

// ===================== MQTT配置 =====================
#define MQTT_PROJECT_ID "1400417"
#define MQTT_DEVICE_ID  "ohk_001"
#define MQTT_SECRET_KEY "c7421564304644c0a134e93c22d73187"

#define MQTT_SERVER     "mqtt.nlecloud.com"
#define MQTT_PORT       1883

#define MQTT_PUB_TOPIC "/sys/" MQTT_PROJECT_ID "/" MQTT_DEVICE_ID "/sensor/datas"
#define MQTT_SUB_TOPIC "/sys/" MQTT_PROJECT_ID "/" MQTT_DEVICE_ID "/sensor/cmdreq"

// ===================== 数据标识名 =====================
#define SENSOR_TEMP     "temperature"
#define SENSOR_HUMI     "humidity"
#define SENSOR_LIGHT    "light"
#define SENSOR_SMOKE    "smoke"
#define SENSOR_R_LIGHT  "r_light"
#define SENSOR_G_LIGHT  "g_light"

// ===================== DHT22 =====================
#define DHTPIN          4
#define DHTTYPE         DHT22

// ===================== LED =====================
#define RED_LED_PIN     2
#define GREEN_LED_PIN   42

// ===================== ADC =====================
#define LDR_PIN         1
#define MQ2_PIN         5

// ===================== 上报周期 =====================
#define REPORT_INTERVAL 1000

WiFiClient espClient;
PubSubClient client(espClient);
DHT dht(DHTPIN, DHTTYPE);

float temperature = 0.0;
float humidity = 0.0;
float lightLux = 0.0;
float smokePPM = 0.0;

unsigned long lastReportTime = 0;

// MQTT错误解析
String getNewlandMQTTError(int code) {
  switch (code) {
    case 0: return "连接成功";
    case 1: return "协议版本错误";
    case 2: return "设备ID错误";
    case 3: return "设备不存在";
    case 4: return "鉴权失败";
    case 5: return "设备未授权";
    default: return "未知错误:" + String(code);
  }
}

// WiFi连接
void connectWiFi() {

  Serial.begin(115200);

  Serial.println();
  Serial.println("ESP32-S3 物联网环境监测系统");

  Serial.print("连接WiFi: ");
  Serial.println(WIFI_NAME);

  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi连接成功");
  Serial.print("IP地址: ");
  Serial.println(WiFi.localIP());
}

// MQTT连接
void connectMQTT() {

  while (!client.connected()) {

    Serial.print("连接MQTT服务器...");

    if (client.connect(
          MQTT_DEVICE_ID,
          MQTT_PROJECT_ID,
          MQTT_SECRET_KEY)) {

      Serial.println("成功");

      client.subscribe(MQTT_SUB_TOPIC);

      Serial.print("已订阅: ");
      Serial.println(MQTT_SUB_TOPIC);

    } else {

      Serial.print("失败: ");
      Serial.println(getNewlandMQTTError(client.state()));

      delay(1000);
    }
  }
}

// ===================== 光照换算 =====================
float getLux() {

  int adc = analogRead(LDR_PIN);

  float voltage = adc * 3.3 / 4095.0;

  if (voltage <= 0.01)
    return 0;

  float resistance =
    2000.0 * voltage /
    (3.3 - voltage);

  float lux =
    pow(
      50.0 * 1000.0 * pow(10, 0.7) / resistance,
      1.0 / 0.7
    );

  if (lux < 0)
    lux = 0;

  return lux;
}

// ===================== MQ2换算 =====================
float getSmokePPM() {

  int adc = analogRead(MQ2_PIN);

  float ppm =
    adc * 10000.0 / 4095.0;

  return ppm;
}

// 读取传感器
void readSensorData() {

  float temp = dht.readTemperature();
  float hum = dht.readHumidity();

  if (!isnan(temp))
    temperature = temp;

  if (!isnan(hum))
    humidity = hum;

  lightLux = getLux();
  smokePPM = getSmokePPM();

  Serial.println();
  Serial.println("========== 传感器数据 ==========");

  Serial.print("温度: ");
  Serial.print(temperature);
  Serial.println(" °C");

  Serial.print("湿度: ");
  Serial.print(humidity);
  Serial.println(" %");

  Serial.print("光照: ");
  Serial.print(lightLux);
  Serial.println(" lx");

  Serial.print("烟雾浓度: ");
  Serial.print(smokePPM);
  Serial.println(" ppm");

  Serial.print("红灯状态: ");
  Serial.println(digitalRead(RED_LED_PIN));

  Serial.print("绿灯状态: ");
  Serial.println(digitalRead(GREEN_LED_PIN));

  Serial.println("================================");
}

// 数据上报
void reportSensorData() {

  if (!client.connected())
    return;

  StaticJsonDocument<512> doc;

  doc["datatype"] = 1;

  JsonObject datas =
    doc.createNestedObject("datas");

  datas[SENSOR_TEMP] = temperature;
  datas[SENSOR_HUMI] = humidity;
  datas[SENSOR_LIGHT] = lightLux;
  datas[SENSOR_SMOKE] = smokePPM;

  datas[SENSOR_R_LIGHT] =
    digitalRead(RED_LED_PIN);

  datas[SENSOR_G_LIGHT] =
    digitalRead(GREEN_LED_PIN);

  String payload;
  serializeJson(doc, payload);

  Serial.println();
  Serial.print("上报数据: ");
  Serial.println(payload);

  if (client.publish(
        MQTT_PUB_TOPIC,
        payload.c_str())) {

    Serial.println("上报成功");

  } else {

    Serial.println("上报失败");
  }
}

// MQTT命令回调
void callback(
  char* topic,
  byte* payload,
  unsigned int length) {

  String message;

  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }

  Serial.println();
  Serial.println("===== 收到平台命令 =====");
  Serial.println(message);

  StaticJsonDocument<256> doc;

  if (deserializeJson(doc, message)) {
    Serial.println("JSON解析失败");
    return;
  }

  String apiTag = doc["apitag"] | "";
  int state = doc["data"] | 0;

  if (apiTag == SENSOR_R_LIGHT) {

    digitalWrite(
      RED_LED_PIN,
      state ? HIGH : LOW);

    Serial.println(
      state ?
      "红色LED开启" :
      "红色LED关闭");
  }

  else if (apiTag == SENSOR_G_LIGHT) {

    digitalWrite(
      GREEN_LED_PIN,
      state ? HIGH : LOW);

    Serial.println(
      state ?
      "绿色LED开启" :
      "绿色LED关闭");
  }

  Serial.println("========================");
}

// 初始化
void setup() {

  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);

  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);

  analogReadResolution(12);

  analogSetPinAttenuation(
    LDR_PIN,
    ADC_11db);

  analogSetPinAttenuation(
    MQ2_PIN,
    ADC_11db);

  connectWiFi();

  dht.begin();

  client.setServer(
    MQTT_SERVER,
    MQTT_PORT);

  client.setCallback(callback);

  connectMQTT();
}

// 主循环
void loop() {

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("WiFi断开，重新连接...");
    WiFi.disconnect();
    connectWiFi();
  }

  if (!client.connected()) {
    connectMQTT();
  }

  client.loop();

  if (millis() - lastReportTime >= REPORT_INTERVAL) {

    lastReportTime = millis();

    readSensorData();

    reportSensorData();
  }

  delay(100);
}
