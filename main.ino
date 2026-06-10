#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>

// ===================== 配置参数 =====================
#define WIFI_NAME       "CirkitWifi"
#define WIFI_PASSWORD   ""

#define MQTT_PROJECT_ID "1400417"
#define MQTT_DEVICE_ID  "ohk_001"
#define MQTT_SECRET_KEY "c7421564304644c0a134e93c22d73187"

// 云平台传感器标识名
#define SENSOR_TEMP     "temperature"
#define SENSOR_HUMI     "humidity"
#define SENSOR_LIGHT    "light"      // LDR光照传感器
#define SENSOR_SMOKE    "smoke"      // MQ2气体传感器
#define SENSOR_R_LIGHT  "r_light"    // 原LED开关
#define SENSOR_G_LIGHT  "g_light"    // 新增绿色LED

// MQTT服务器
#define MQTT_SERVER     "mqtt.nlecloud.com"
#define MQTT_PORT       1883

// MQTT主题
#define MQTT_PUB_TOPIC "/sys/" MQTT_PROJECT_ID "/" MQTT_DEVICE_ID "/sensor/datas"
#define MQTT_SUB_TOPIC "/sys/" MQTT_PROJECT_ID "/" MQTT_DEVICE_ID "/sensor/cmdreq"

// DHT22配置
#define DHTPIN 4
#define DHTTYPE DHT22

// LED引脚
#define LED_PIN 2      // 原红色LED
#define G_LED_PIN 42   // 新增绿色LED

// LDR/MQ2引脚
#define LDR_PIN 35
#define MQ2_PIN 36

// 数据上报间隔（毫秒）
#define REPORT_INTERVAL 1000
// ====================================================

WiFiClient espClient;
PubSubClient client(espClient);
DHT dht(DHTPIN, DHTTYPE);

float temperature = 0.0;
float humidity = 0.0;
int lightValue = 0;
int smokeValue = 0;
unsigned long lastReportTime = 0;

// MQTT连接错误解析
String getNewlandMQTTError(int returnCode) {
  switch (returnCode) {
    case 0: return "连接成功";
    case 1: return "协议版本错误（仅支持3.1.1）";
    case 2: return "设备ID长度超限";
    case 3: return "设备未在平台添加";
    case 4: return "鉴权失败（项目ID或密钥错误）";
    case 5: return "设备未授权连接";
    default: return "未知错误（码：" + String(returnCode) + ")";
  }
}

// WiFi连接
void connectWiFi() {
  Serial.begin(115200);
  Serial.println();
  Serial.print("正在连接WiFi: ");
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
    Serial.print("连接新大陆MQTT服务器...");
    if (client.connect(MQTT_DEVICE_ID, MQTT_PROJECT_ID, MQTT_SECRET_KEY)) {
      Serial.println("成功");
      if (client.subscribe(MQTT_SUB_TOPIC)) {
        Serial.print("已订阅主题: ");
        Serial.println(MQTT_SUB_TOPIC);
      }
    } else {
      Serial.print("失败: ");
      Serial.println(getNewlandMQTTError(client.state()));
      delay(1000);
    }
  }
}

// 读取传感器数据
void readSensorData() {
  float temp = dht.readTemperature();
  float hum = dht.readHumidity();
  if (!isnan(temp)) temperature = temp;
  if (!isnan(hum)) humidity = hum;

  lightValue = analogRead(LDR_PIN);
  smokeValue = analogRead(MQ2_PIN);

  Serial.print("温度: "); Serial.print(temperature); Serial.print(" °C  ");
  Serial.print("湿度: "); Serial.print(humidity); Serial.print(" %  ");
  Serial.print("光照: "); Serial.print(lightValue); Serial.print("  ");
  Serial.print("烟雾: "); Serial.println(smokeValue);
}

// 上报数据
void reportSensorData() {
  if (!client.connected()) return;

  StaticJsonDocument<512> doc;
  doc["datatype"] = 1;
  JsonObject datas = doc.createNestedObject("datas");

  datas[SENSOR_TEMP] = temperature;
  datas[SENSOR_HUMI] = humidity;
  datas[SENSOR_LIGHT] = lightValue;
  datas[SENSOR_SMOKE] = smokeValue;
  datas[SENSOR_R_LIGHT] = digitalRead(LED_PIN);
  datas[SENSOR_G_LIGHT] = digitalRead(G_LED_PIN);

  String payload;
  serializeJson(doc, payload);

  Serial.print("上报数据: "); Serial.println(payload);
  if (client.publish(MQTT_PUB_TOPIC, payload.c_str())) {
    Serial.println("上报成功");
  } else {
    Serial.println("上报失败");
  }
}

// MQTT消息回调
void callback(char* topic, byte* payload, unsigned int length) {
  Serial.println();
  Serial.println("===== 收到平台命令 =====");
  Serial.print("主题: "); Serial.println(topic);

  String message = "";
  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  Serial.print("命令内容: "); Serial.println(message);

  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, message);
  if (error) {
    Serial.println("JSON解析失败");
    return;
  }

  String apiTag = doc["apitag"] | "";
  int state = doc["data"] | 0;

  if (apiTag == SENSOR_R_LIGHT) {
    digitalWrite(LED_PIN, state ? HIGH : LOW);
    Serial.println(state ? "红色LED开启" : "红色LED关闭");
  }
  else if (apiTag == SENSOR_G_LIGHT) {
    digitalWrite(G_LED_PIN, state ? HIGH : LOW);
    Serial.println(state ? "绿色LED开启" : "绿色LED关闭");
  }

  Serial.println("========================");
  Serial.println();
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  pinMode(G_LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(G_LED_PIN, LOW);

  connectWiFi();
  dht.begin();

  client.setServer(MQTT_SERVER, MQTT_PORT);
  client.setCallback(callback);
  connectMQTT();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi断开，重新连接...");
    WiFi.disconnect();
    connectWiFi();
  }
  if (!client.connected()) connectMQTT();
  client.loop();

  if (millis() - lastReportTime >= REPORT_INTERVAL) {
    lastReportTime = millis();
    readSensorData();
    reportSensorData();
  }

  delay(100);
}
