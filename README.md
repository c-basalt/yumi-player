# Yumi点歌姬

### Yumi点歌姬是
- B站直播间的点歌姬
- 歌单、弹幕点歌的播放器
- OBS浏览器源的BGM播放器
- 本地运行的工具
- 下载完成后才播放的播放器
- 仅限声音的播放器

### Yumi点歌姬**不是**
- 其他网站的弹幕工具
- 记录"点歌 XXX"弹幕用的点歌板
- 弹幕姬、伴奏、歌词工具
- 数据部署在服务器的在线工具
- 边下边播的播放器
- 提供视频画面的播放器

## 使用

启动Yumi点歌姬程序后会自动在浏览器打开控制页面。控制页面中完成配置后，点击“复制OBS播放器链接”。在OBS或直播姬中，添加浏览器源，然后在URL部分粘贴链接即可。使用时需要保持Yumi点歌姬程序的命令行窗口运行。

## 核心设计

Yumi点歌姬在收到弹幕点歌后，会立刻下载完整的歌曲文件，直到下载完成后才会将歌曲加入播放队列，这意味着：
- 从发出弹幕到点歌成功，需要10秒到半分钟（取决于网速和文件大小）
- 需要预留硬盘空间存储缓存歌曲 (每首约3-10MB，可修改总存储上限)

但是：
- 不会因为网络波动中途播放卡住
- 点歌成功=能播放，不会点歌成功后才发现失败被跳过

## 主要功能

- 观众发送"点歌 歌名"弹幕，从QQ音乐/网易云点歌进行播放
- 添加B站、QQ音乐、网易云歌单，空闲时从添加的歌单随机播放。歌单支持：
    - 网易云、QQ音乐的常规歌单
    - B站的分P视频
    - B站的合集、系列、收藏
- 在本地控制台页面支持
    - 手动从B站、QQ音乐、网易云点歌
    - 将最近弹幕中的BV号作为点歌加入播放队列
    - 删除/跳过/拖拽排序队列中歌曲
- 音频均衡功能
    - 根据全曲的平均分贝降低音量（但不增大平均分贝低于设置值的音量）
    - 默认值为-40dB，大致相当于5%级别的音量
    - 建议搭配OBS混音器中的电平表，对比其他音量调整至合适水平
- 点歌的历史记录
    - 查看歌名、点歌人、点歌时间
    - 再次添加相同歌曲到播放队列

## 配置

### 身份码

身份码的接口更改频繁且有数据缺失，故本项目不会支持身份码连接弹幕，但你可以在开源协议允许的前提下fork后自行实现

### 登录站点

虽然Yumi点歌姬设计上无需登录就能用，但是有时候歌曲资源需要登录后才能获取。
Yumi点歌姬不直接提供登录界面，不存储登录状态，也不会给用户提供在配置中填写具体Cookie的选项。
作为替代，Yumi点歌姬可以使用[rookie](https://github.com/thewh1teagle/rookie)或者[CookieCloud](https://github.com/easychen/CookieCloud)来使用浏览器中已有的登录。

具体来说，用户可以下载一个[Chromium浏览器](https://storage.googleapis.com/chromium-browser-snapshots/index.html?prefix=Win_x64/1300320/)，在浏览器中打开相应站点网页进行登录。然后启动Yumi点歌姬进入设置页面，在相应站点中选择Chromium来加载浏览器中的登录状态。（注意：Chromium和Chrome是不同的浏览器）
或者在Chromium浏览器中安装CookieCloud扩展后，按照Yumi点歌姬设置页面中的说明对CookieCloud进行配置。

### 后备属性

播放队列中的歌曲可以设置后备属性，这个机制允许：
- 后备的歌曲（除非正在播放）不会显示在浏览器源的待播的列表中
- 只有非后备的歌曲全部放完才会播放后备的歌曲

从歌单自动添加的歌曲默认为后备属性，但是在开始播放时会自动转成非后备属性。也可以在选项中关闭，这样有新点歌时会立刻中断后备歌曲，播放新点歌。

## 手动从源代码运行（Windows）

按照教程安装npm、Python 3.10或更高版本，并下载ffmpeg到当前目录或添加到PATH

打包前端
```cmd
cd frontend
npm install
npm run build
```

安装Python依赖

```cmd
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

运行

```cmd
.venv\Scripts\activate
py main.py
```

## 开发者功能

Yumi点歌姬也支持CookieCloud的客户端模式，但不会以常规配置选项提供给一般用户。因为CookieCloud的密钥只有64位，使用公共服务器存在被暴力破解、泄露所有网站账号信息的风险，同时搭建服务器和管理密码对普通用户门槛过高

对于有能力的开发者，可通过以下两种方式配置CookieCloud客户端：
- 设置 `COOKIE_CLOUD_URL` 环境变量为URL
- 在程序加载后发送 `POST /api/cookie` 请求，请求体为 `{"cookie_cloud_url": <url>}`

URL需包含CookieCloud服务器地址，并以Basic Auth形式在URL中提供uuid和密码。配置成功后，客户端将作为浏览器选项之一显示（与chrome、firefox等并列）
