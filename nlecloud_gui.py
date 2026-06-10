# -*- coding: utf-8 -*-
"""NLECloud 图形化监控客户端。"""

import json
import os
import queue
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import messagebox, ttk

BASE_URL = "http://api.nlecloud.com"
TOKEN_FILE = "token.json"
POLL_INTERVAL_SECONDS = 3
MAX_POINTS_PER_TAG = 60
DEFAULT_TEMPERATURE_THRESHOLD = 30.0
TEMPERATURE_TAG_KEYWORDS = ("temp", "temperature", "temper", "温度", "wendu")


class NLECloudClient:
    """NLECloud API 的轻量封装，负责登录、Token 持久化和实时数据请求。"""

    def __init__(self, base_url=BASE_URL, token_file=TOKEN_FILE):
        self.base_url = base_url.rstrip("/")
        self.token_file = token_file
        self.access_token = ""
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request_json(self, method, url, **kwargs):
        params = kwargs.get("params")
        json_body = kwargs.get("json")
        if params:
            query = urllib.parse.urlencode(params)
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"

        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")

        request = urllib.request.Request(url, data=body, method=method.upper(), headers=self.headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)

    def load_token(self):
        if not os.path.exists(self.token_file):
            return False
        with open(self.token_file, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        token = data.get("access_token", "")
        if not token:
            return False
        self.access_token = token
        self.headers.update({"AccessToken": token})
        return True

    def save_token(self):
        with open(self.token_file, "w", encoding="utf-8") as file_obj:
            json.dump({"access_token": self.access_token}, file_obj, ensure_ascii=False, indent=2)

    def clear_token(self):
        self.access_token = ""
        self.headers.pop("AccessToken", None)
        if os.path.exists(self.token_file):
            os.remove(self.token_file)

    def login(self, username, password):
        data = self.request_json(
            "POST",
            f"{self.base_url}/Users/Login",
            json={"Account": username, "Password": password, "IsRememberMe": True},
        )
        if data.get("Status") != 0:
            raise RuntimeError("登录失败：" + str(data.get("Msg", "未知错误")))
        self.access_token = data["ResultObj"]["AccessToken"]
        self.headers.update({"AccessToken": self.access_token})
        self.save_token()
        return data

    def get_realtime(self, device_id):
        return self.request_json("GET", f"{self.base_url}/Devices/Datas", params={"devIds": device_id})

    def send_command(self, device_id, api_tag, value):
        return self.request_json(
            "POST",
            f"{self.base_url}/Cmds",
            params={"deviceId": device_id, "apiTag": api_tag},
            json=value,
        )


class RealtimeChart(tk.Canvas):
    """使用 tkinter Canvas 绘制实时折线图，避免额外图表依赖。"""

    COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#17becf"]

    def __init__(self, master, **kwargs):
        super().__init__(master, background="white", highlightthickness=1, highlightbackground="#d0d7de", **kwargs)
        self.series = {}
        self.bind("<Configure>", lambda event: self.draw())

    def set_series(self, series):
        self.series = series
        self.draw()

    def draw(self):
        self.delete("all")
        width = max(self.winfo_width(), 200)
        height = max(self.winfo_height(), 160)
        left, top, right, bottom = 56, 24, 20, 44
        plot_w = width - left - right
        plot_h = height - top - bottom

        self.create_text(width // 2, 12, text="实时数据趋势", fill="#24292f", font=("Arial", 12, "bold"))
        self.create_line(left, top, left, top + plot_h, fill="#8c959f")
        self.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill="#8c959f")

        numeric_points = []
        for points in self.series.values():
            numeric_points.extend(value for _, value in points)
        if not numeric_points:
            self.create_text(width // 2, height // 2, text="暂无可绘制的数值数据", fill="#6e7781")
            return

        min_value = min(numeric_points)
        max_value = max(numeric_points)
        if min_value == max_value:
            min_value -= 1
            max_value += 1
        value_span = max_value - min_value
        max_len = max(len(points) for points in self.series.values() if points)
        x_span = max(max_len - 1, 1)

        for idx in range(5):
            y = top + plot_h * idx / 4
            value = max_value - value_span * idx / 4
            self.create_line(left, y, left + plot_w, y, fill="#eaeef2")
            self.create_text(left - 8, y, text=f"{value:.2f}", anchor="e", fill="#57606a", font=("Arial", 9))

        for series_index, (tag, points) in enumerate(self.series.items()):
            if not points:
                continue
            color = self.COLORS[series_index % len(self.COLORS)]
            coords = []
            for point_index, (_, value) in enumerate(points):
                x = left + plot_w * point_index / x_span
                y = top + plot_h - (value - min_value) * plot_h / value_span
                coords.extend([x, y])
            if len(coords) >= 4:
                self.create_line(*coords, fill=color, width=2, smooth=True)
            for x, y in zip(coords[0::2], coords[1::2]):
                self.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline=color)
            legend_x = left + 8 + (series_index % 3) * 160
            legend_y = height - 28 + (series_index // 3) * 14
            self.create_line(legend_x, legend_y, legend_x + 22, legend_y, fill=color, width=3)
            self.create_text(legend_x + 28, legend_y, text=tag, anchor="w", fill="#24292f", font=("Arial", 9))

        self.create_text(left + plot_w // 2, height - 10, text=f"最近 {MAX_POINTS_PER_TAG} 个采样点", fill="#57606a")


class NLECloudApp(tk.Tk):
    """NLECloud 登录、监控和图形化展示主界面。"""

    def __init__(self):
        super().__init__()
        self.title("NLECloud 图形化监控")
        self.geometry("1080x760")
        self.minsize(920, 640)

        self.client = NLECloudClient()
        self.message_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.command_lock = threading.Lock()
        self.monitor_thread = None
        self.series = {}
        self.latest_rows = {}
        self.last_auto_command = None

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.device_id_var = tk.StringVar()
        self.status_var = tk.StringVar(value="未登录")
        self.poll_interval_var = tk.IntVar(value=POLL_INTERVAL_SECONDS)
        self.temperature_threshold_var = tk.DoubleVar(value=DEFAULT_TEMPERATURE_THRESHOLD)
        self.temperature_threshold_label_var = tk.StringVar(value=self._format_temperature_threshold())
        self.actuator_tag_var = tk.StringVar()
        self.auto_control_var = tk.BooleanVar(value=True)
        self.control_status_var = tk.StringVar(value="执行器控制待命")

        self._build_ui()
        self._load_saved_token()
        self.after(150, self._process_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        login_frame = ttk.LabelFrame(root, text="登录", padding=10)
        login_frame.grid(row=0, column=0, sticky="ew")
        for idx in range(9):
            login_frame.columnconfigure(idx, weight=0)
        login_frame.columnconfigure(8, weight=1)

        ttk.Label(login_frame, text="用户名").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(login_frame, textvariable=self.username_var, width=22).grid(row=0, column=1, padx=(0, 12))
        ttk.Label(login_frame, text="密码").grid(row=0, column=2, padx=(0, 6))
        ttk.Entry(login_frame, textvariable=self.password_var, show="*", width=22).grid(row=0, column=3, padx=(0, 12))
        ttk.Button(login_frame, text="登录", command=self.login).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(login_frame, text="读取已保存 Token", command=self.load_token_from_button).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(login_frame, text="退出登录", command=self.logout).grid(row=0, column=6, padx=(0, 8))
        ttk.Label(login_frame, textvariable=self.status_var, foreground="#0969da").grid(row=0, column=8, sticky="e")

        monitor_frame = ttk.LabelFrame(root, text="监控", padding=10)
        monitor_frame.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        monitor_frame.columnconfigure(6, weight=1)
        ttk.Label(monitor_frame, text="设备ID").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(monitor_frame, textvariable=self.device_id_var, width=24).grid(row=0, column=1, padx=(0, 12))
        ttk.Label(monitor_frame, text="刷新间隔(秒)").grid(row=0, column=2, padx=(0, 6))
        ttk.Spinbox(monitor_frame, from_=1, to=60, textvariable=self.poll_interval_var, width=6).grid(row=0, column=3, padx=(0, 12))
        self.monitor_button = ttk.Button(monitor_frame, text="开始监控", command=self.toggle_monitor)
        self.monitor_button.grid(row=0, column=4, padx=(0, 8))
        ttk.Button(monitor_frame, text="清空图表", command=self.clear_chart).grid(row=0, column=5, padx=(0, 8))

        control_frame = ttk.LabelFrame(root, text="温度自动/手动控制", padding=10)
        control_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        control_frame.columnconfigure(10, weight=1)
        ttk.Label(control_frame, text="温度阈值(℃)").grid(row=0, column=0, padx=(0, 6))
        temperature_slider = ttk.Scale(
            control_frame,
            from_=0,
            to=100,
            variable=self.temperature_threshold_var,
            command=self._on_temperature_threshold_changed,
            length=220,
        )
        temperature_slider.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        ttk.Label(control_frame, textvariable=self.temperature_threshold_label_var, width=8).grid(row=0, column=2, padx=(0, 16))
        ttk.Label(control_frame, text="传感器标识名").grid(row=0, column=3, padx=(0, 6))
        ttk.Entry(control_frame, textvariable=self.actuator_tag_var, width=20).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(control_frame, text="手动打开", command=lambda: self.manual_control(True)).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(control_frame, text="手动关闭", command=lambda: self.manual_control(False)).grid(row=0, column=6, padx=(0, 12))
        ttk.Checkbutton(control_frame, text="启用自动控制", variable=self.auto_control_var).grid(row=0, column=7, padx=(0, 12))
        ttk.Label(control_frame, textvariable=self.control_status_var, foreground="#0969da").grid(
            row=0, column=10, sticky="e"
        )

        ttk.Label(
            control_frame,
            text="自动规则：实时温度 > 阈值时打开该标识名，否则关闭；温度从 ApiTag/名称含 temp、temperature、温度、wendu 的数值数据中读取。",
            foreground="#57606a",
        ).grid(row=1, column=0, columnspan=11, sticky="w", pady=(8, 0))

        content = ttk.PanedWindow(root, orient="vertical")
        content.grid(row=3, column=0, sticky="nsew")

        table_frame = ttk.LabelFrame(content, text="实时数据", padding=8)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = ("device", "tag", "value", "time")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=9)
        self.tree.heading("device", text="设备")
        self.tree.heading("tag", text="ApiTag")
        self.tree.heading("value", text="当前值")
        self.tree.heading("time", text="记录时间")
        self.tree.column("device", width=180)
        self.tree.column("tag", width=180)
        self.tree.column("value", width=140)
        self.tree.column("time", width=220)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        chart_frame = ttk.LabelFrame(content, text="图形化趋势", padding=8)
        chart_frame.rowconfigure(0, weight=1)
        chart_frame.columnconfigure(0, weight=1)
        self.chart = RealtimeChart(chart_frame, height=300)
        self.chart.grid(row=0, column=0, sticky="nsew")

        content.add(table_frame, weight=1)
        content.add(chart_frame, weight=3)

    def _load_saved_token(self):
        try:
            if self.client.load_token():
                self.status_var.set("已加载保存的 Token，可直接监控")
        except (OSError, json.JSONDecodeError) as exc:
            self.status_var.set(f"Token 读取失败：{exc}")

    def load_token_from_button(self):
        if self.client.load_token():
            self.status_var.set("已加载保存的 Token")
            messagebox.showinfo("Token", "已读取本地保存的 Token。")
        else:
            messagebox.showwarning("Token", "未找到可用的本地 Token，请输入用户名和密码登录。")

    def login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        if not username or not password:
            messagebox.showwarning("登录", "请输入用户名和密码。")
            return
        self.status_var.set("正在登录...")
        threading.Thread(target=self._login_worker, args=(username, password), daemon=True).start()

    def _login_worker(self, username, password):
        try:
            self.client.login(username, password)
            self.message_queue.put(("login_ok", "登录成功，Token 已保存。"))
        except (urllib.error.URLError, KeyError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            self.message_queue.put(("error", f"登录失败：{exc}"))

    def logout(self):
        self.stop_monitor()
        self.client.clear_token()
        self.status_var.set("已退出登录")
        messagebox.showinfo("退出登录", "本地 Token 已清除。")

    def toggle_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        if not self.client.access_token:
            messagebox.showwarning("监控", "请先登录或读取已保存 Token。")
            return
        device_id = self.device_id_var.get().strip()
        if not device_id:
            messagebox.showwarning("监控", "请输入设备ID。")
            return
        self.stop_event.clear()
        self.monitor_button.configure(text="停止监控")
        self.status_var.set(f"正在监控设备 {device_id} ...")
        interval = max(1, int(self.poll_interval_var.get() or POLL_INTERVAL_SECONDS))
        self.monitor_thread = threading.Thread(target=self._monitor_worker, args=(device_id, interval), daemon=True)
        self.monitor_thread.start()

    def stop_monitor(self):
        self.stop_event.set()
        self.monitor_button.configure(text="开始监控")
        if self.client.access_token:
            self.status_var.set("监控已停止")

    def _monitor_worker(self, device_id, interval):
        while not self.stop_event.is_set():
            try:
                data = self.client.get_realtime(device_id)
                self.message_queue.put(("realtime", data))
            except (urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self.message_queue.put(("error", f"获取实时数据失败：{exc}"))
            for _ in range(interval * 10):
                if self.stop_event.is_set():
                    break
                time.sleep(0.1)
        self.message_queue.put(("monitor_stopped", None))

    def _process_queue(self):
        while True:
            try:
                event, payload = self.message_queue.get_nowait()
            except queue.Empty:
                break
            if event == "login_ok":
                self.status_var.set(payload)
                messagebox.showinfo("登录", payload)
            elif event == "realtime":
                self._apply_realtime(payload)
            elif event == "monitor_stopped":
                self.monitor_button.configure(text="开始监控")
            elif event == "command_ok":
                self.control_status_var.set(payload)
            elif event == "command_error":
                self.last_auto_command = None
                self.control_status_var.set(payload)
            elif event == "error":
                self.status_var.set(payload)
                messagebox.showerror("错误", payload)
        self.after(150, self._process_queue)

    def _apply_realtime(self, data):
        if data.get("Status") not in (0, None):
            self.status_var.set("接口返回错误：" + str(data.get("Msg", "未知错误")))
            return
        devices = data.get("ResultObj", [])
        row_count = 0
        temperature_value = self._extract_temperature_value(devices)
        for device in devices:
            device_name = device.get("Name") or str(device.get("DeviceID", "未知设备"))
            for item in device.get("Datas", []):
                tag = str(item.get("ApiTag", ""))
                value = item.get("Value", "")
                record_time = item.get("RecordTime", "")
                row_id = f"{device.get('DeviceID', device_name)}::{tag}"
                values = (device_name, tag, value, record_time)
                if row_id in self.latest_rows:
                    self.tree.item(row_id, values=values)
                else:
                    self.tree.insert("", "end", iid=row_id, values=values)
                    self.latest_rows[row_id] = True
                self._append_chart_point(tag, value, record_time)
                row_count += 1
        self.chart.set_series(self.series)
        self._run_auto_temperature_control(temperature_value)
        self.status_var.set(f"最新刷新：{time.strftime('%Y-%m-%d %H:%M:%S')}，更新 {row_count} 条数据")

    def _extract_temperature_value(self, devices):
        for device in devices:
            for item in device.get("Datas", []):
                tag = str(item.get("ApiTag", ""))
                name = str(item.get("Name", ""))
                searchable = f"{tag} {name}".lower()
                if any(keyword in searchable for keyword in TEMPERATURE_TAG_KEYWORDS):
                    try:
                        return float(item.get("Value", ""))
                    except (TypeError, ValueError):
                        continue
        return None

    def _run_auto_temperature_control(self, temperature_value):
        if not self.auto_control_var.get():
            return
        if temperature_value is None:
            self.control_status_var.set("未找到温度数据，自动控制未执行")
            return
        threshold = float(self.temperature_threshold_var.get())
        should_open = temperature_value > threshold
        if should_open == self.last_auto_command:
            self.control_status_var.set(
                f"自动控制保持{'打开' if should_open else '关闭'}：温度 {temperature_value:.1f}℃，阈值 {threshold:.1f}℃"
            )
            return
        reason = f"自动控制：温度 {temperature_value:.1f}℃ {'>' if should_open else '<='} 阈值 {threshold:.1f}℃"
        self._send_actuator_command(should_open, reason=reason, show_validation_popup=False)

    def _format_temperature_threshold(self):
        return f"{float(self.temperature_threshold_var.get()):.1f}℃"

    def _on_temperature_threshold_changed(self, _value=None):
        self.temperature_threshold_label_var.set(self._format_temperature_threshold())
        self.last_auto_command = None

    def manual_control(self, open_state):
        self._send_actuator_command(open_state, reason="手动控制", show_validation_popup=True)

    def _send_actuator_command(self, open_state, reason, show_validation_popup):
        if not self.client.access_token:
            self.control_status_var.set("自动控制未执行：请先登录或读取已保存 Token")
            if show_validation_popup:
                messagebox.showwarning("执行器控制", "请先登录或读取已保存 Token。")
            return False
        device_id = self.device_id_var.get().strip()
        if not device_id:
            self.control_status_var.set("自动控制未执行：请输入设备ID")
            if show_validation_popup:
                messagebox.showwarning("执行器控制", "请输入设备ID。")
            return False
        api_tag = self.actuator_tag_var.get().strip()
        if not api_tag:
            self.control_status_var.set("自动控制未执行：请输入要控制的传感器标识名")
            if show_validation_popup:
                messagebox.showwarning("执行器控制", "请输入要控制的传感器标识名。")
            return False

        command_value = 1 if open_state else 0
        state_text = "打开" if open_state else "关闭"
        self.control_status_var.set(f"正在{state_text} {api_tag} ...")
        if reason.startswith("自动控制"):
            self.last_auto_command = open_state
        else:
            self.last_auto_command = None
        threading.Thread(
            target=self._command_worker,
            args=(device_id, api_tag, command_value, reason),
            daemon=True,
        ).start()
        return True

    def _command_worker(self, device_id, api_tag, command_value, reason):
        with self.command_lock:
            try:
                data = self.client.send_command(device_id, api_tag, command_value)
                if data.get("Status") not in (0, None):
                    raise RuntimeError(str(data.get("Msg", "未知错误")))
                state_text = "打开" if command_value == 1 else "关闭"
                self.message_queue.put(("command_ok", f"{reason}，{api_tag} 已{state_text}"))
            except (urllib.error.URLError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self.message_queue.put(("command_error", f"命令发送失败：{exc}"))

    def _append_chart_point(self, tag, value, record_time):
        if not tag:
            return
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return
        points = self.series.setdefault(tag, [])
        points.append((record_time or time.strftime("%H:%M:%S"), numeric_value))
        if len(points) > MAX_POINTS_PER_TAG:
            del points[: len(points) - MAX_POINTS_PER_TAG]

    def clear_chart(self):
        self.series.clear()
        self.chart.set_series(self.series)
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        self.latest_rows.clear()
        self.status_var.set("图表和实时数据已清空")

    def _on_close(self):
        self.stop_event.set()
        self.destroy()


def main():
    app = NLECloudApp()
    app.mainloop()


if __name__ == "__main__":
    main()
