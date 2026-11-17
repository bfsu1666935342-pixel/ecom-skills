# 交付前检查 · QA Checklist

## 数据

- [ ] `doctor` 通过；没有缺映射工具
- [ ] 类目 Node 已确认；没有用相近类目代替
- [ ] 站点正确（US/GB/DE…）
- [ ] 数据窗口 ≥ 12 个月；最好 24 个月
- [ ] `data.json` 的 `products` 不是空
- [ ] `months` / `sales` / `revenue` 长度一致
- [ ] Top100 销量与类目报告量级一致（差 < 5%）
- [ ] 价格带 4 段的销量/销售额份额合计约 100%
- [ ] 评论分层 ASIN 占比约 100%
- [ ] 关键词有 `term / volume / cpc`；没有的字段是 null，不是 0
- [ ] 缺的模块全部写进 `gaps`

## 判断

- [ ] 5 个 gate 都有 `pass/warn/fail/unknown`
- [ ] 有 hard fail 时 verdict 不是 Go
- [ ] supply unknown 时 verdict 不是 Go
- [ ] `total_score` = 加权分（±1）
- [ ] 结论里的数字能在 `data.json` 找到
- [ ] 成本假设和实测数据分开写
- [ ] 没有“大概/可能/应该”代替数字
- [ ] 明确写了“不做什么”

## 报告

- [ ] `build_report.py` 成功
- [ ] `verify_report.py` PASS
- [ ] 没有 `__DATA__` / `__NARRATIVE__` / `undefined` / `NaN`
- [ ] 6 个 tab 都能切换
- [ ] 改价格 / landed / CPC / CVR，经济性会重算
- [ ] 商品 ASIN 链接可点
- [ ] 手机宽度不横向溢出（表格可横滑）
- [ ] 打印 / PDF 包含全部 tab
- [ ] 页面顶部有数据源、日期、第三方估算声明
- [ ] 页面没有 API key

## 交付

- [ ] `report.html`
- [ ] `data.json`
- [ ] `narrative.json`
- [ ] 原始 `raw/`（至少保留类目报告 + 商品 + 关键词）
- [ ] 说明：站点、Node、窗口、来源、假设、缺口

## 回归

改模板或脚本后，先跑 golden case：

```bash
python scripts/build_report.py --slug drafting-chair --root examples
python scripts/verify_report.py --slug drafting-chair --root examples
```

两者都通过，再跑新类目。
