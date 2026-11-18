# templates

目前模板内嵌在 `scripts/wr/render.py`：

- `CSS`：屏幕预览样式（不影响飞书粘贴）
- `TABLE` / `TH` / `TD`：表格内联样式（粘贴后保留边框、底色、对齐）
- `COPY_JS`：右上角「复制到飞书」富文本复制

要换版式，直接改 `render.py` 里的 `CSS` 和 `_table()`；不要把 HTML 拆成 Jinja 之类的模板文件，少一层构建更稳。
