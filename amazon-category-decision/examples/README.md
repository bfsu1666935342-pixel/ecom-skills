# Golden case · Drafting Chair

这是 skill 的回归样本：同一份 `data.json + narrative.json` 应该稳定生成同样的结论和版式。

- `data.json`：从 Sorftime MCP 2026-11-12 的 Drafting Chairs Top100 归一化
- `narrative.json`：按 `reference/rubric.md` 写的判断
- `report.html`：固定模板生成
- `preview.png`：总览预览

重建 / 校验：

```bash
python scripts/build_report.py --slug drafting-chair --root examples
python scripts/verify_report.py --slug drafting-chair --root examples
```

不要改 `report.html` 来“修”结论；改 `data.json` 或 `narrative.json`，再 build。
