# pass

- 安装依赖

```bash
pip install -r requirements.txt
```

- 不要自行创建任何文档

## pdf转图片 split.py

- 把护照 pdf/1.pdf 每页转成图片存入 img/ 目录下

## 调整图片角度 rotate.py

- 摆正每页护照图片 调整角度需要微调 不是简单的90度调整
- 护照首页 末页 黑色封面 调整角度后 竖着摆正
- 护照中间页 页码数字在底下左右两测 调整角度 水平摆正

## 删除多余背景 remove.py

- 每页护照图片 删除多余背景
