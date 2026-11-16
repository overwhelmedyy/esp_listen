# 西语听力（esp_listen）

播放 *Spanish for False Beginners* 播客音频，同时显示西英对照文本（手动滑动）。

## 使用

1. 在 [Releases](../../releases) 下载最新的 `esp_listen-v1.0.x.apk` 安装
2. 把电脑上 `F:\esp_audio\audio` 整个文件夹复制到手机（比如 `Music/esp_audio`）
3. 打开 App，点「选择音频文件夹」选中这个文件夹（只需一次）
4. 点任意一集开始听

音频按文件名里的 YouTube ID（`[xxxxxxxxxxx]`）匹配，文件名其他部分改了也没关系。

## 播放页操作

- 底部大按钮：«10 秒 · ‹5 秒 · 播放/暂停 · 5 秒› · 10 秒»
- 下面一排一键变速：0.75× 0.85× 1× 1.15× 1.25× 1.5×
- 顶部：A− / A+ 调字号，EN 显示/隐藏英文
- 锁屏、切到别的 App 继续播放；通知栏和锁屏有 -10 秒 / 播放暂停 / +10 秒；耳机线控可用
- 每集自动记住播放进度和文本滚动位置

## 注释（点按单词）

- 词义（英文，来自 Wiktionary）、动词变位、语法结构（橙色虚线）、固定搭配（绿色下划线）、宾语（可在设置里打开）、性数一致（词尾 4 色）
- 由 spaCy 自动分析 + 规则生成，准确率约九成；`tools/phrase_blacklist.txt` 里是排除掉的误匹配搭配

## 手动对齐

播放页右上角「对齐」：听到高亮句开头时按「标记本句开始」，可撤销、±0.2 秒微调。标完的集播放时自动高亮当前句并跟随滚动。设置里可以导出/导入备份；把备份文件放进 `web/align.json` 可以打包进 app。

## 项目结构

- `web/index.html` 界面（在电脑浏览器里也能直接打开测试：选择音频文件夹后用 `<audio>` 播放）
- `web/transcripts.json` 全部剧集的双语文本，由 `tools/build_data.py` 从 PDF 生成
- `web/ann/<n>.json`、`web/lex.json` 注释数据：`tools/nlp_pass.py`（spaCy）→ `tools/build_ann.py`
- `web/align.json` 内置的对齐时间（可选）
- `app/` 安卓原生壳：WebView + MediaPlayer 前台服务 + 系统文件夹选择
- 推送到 main 自动用 GitHub Actions 编译并发布 APK
