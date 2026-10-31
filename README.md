# 安装依赖
```text
pip install -r requirements.txt --break-system-packages
```
# 获取 Qobuz X-User-Auth-Token

1. 使用浏览器登录 Qobuz。
2. 按 F12 打开开发者工具。
3. 切换到 Network（网络） 标签。
4. 刷新网页，选择任意一个 Qobuz API 请求。
5. 在 Request Headers（请求标头） 中找到 X-User-Auth-Token。
6. 复制 Token，并填写到项目根目录的 config.yaml 中。

# 启动服务
```text
python3 main.py
```

<img width="1754" height="2058" alt="1" src="https://github.com/user-attachments/assets/84451318-7207-425a-8ea1-01161e270658" />

<img width="3596" height="2012" alt="2" src="https://github.com/user-attachments/assets/fcc542ce-9991-44c5-a126-f56c218cb71a" />

