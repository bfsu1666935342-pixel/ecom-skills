# SIF 适配说明

SIF 和 Sorftime 都走 MCP 时，差异只在**工具名**。抓数流程、schema、报告模板完全共用。

## 1. 填连接信息

`.env`：

```dotenv
SIF_MCP_URL=你的 SIF MCP endpoint
SIF_MCP_KEY=你的 key
```

## 2. 看 SIF 实际暴露了哪些工具

```bash
python scripts/ecom_skill.py doctor --provider sif --list-tools
```

会输出 SIF MCP 的 `tools` 列表。

## 3. 填工具映射

编辑 `config/providers.json` → `sif.tools`。标准键：

| 标准键 | 用途 | Sorftime 对应 |
| --- | --- | --- |
| `category_search` | 类目名 → node | `category_name_search` |
| `category_report` | 类目 19 项统计 | `category_report` |
| `category_products` | Top100 商品 | `category_products` |
| `category_keywords` | 类目核心词 | `category_keywords` |
| `category_trend` | 销量/价格/Amazon 份额趋势 | `category_trend` |
| `keyword_detail` | 关键词 CPC/CVR/首页 | `keyword_detail` |
| `keyword_trend` | 关键词 24 个月趋势 | `keyword_trend` |
| `keyword_search_results` | 关键词自然位商品 | `keyword_search_results` |
| `product_detail` | 单个 ASIN 详情 | `product_detail` |
| `product_customers_say` | 评论摘要 | `product_customers_say` |
| `product_content` | 图片/属性/A+ | `product_content` |

把 SIF 的实际工具名填进去，例如：

```json
"sif": {
  "tools": {
    "category_search": "sif_category_search",
    "category_report": "sif_category_report",
    "category_products": "sif_category_products"
  }
}
```

没填的键会在 `doctor` 里报 `missing_mapped_tools`；不要跳过，否则 fetch 到一半才失败。

## 4. 参数差异

如果 SIF 的参数名不同（例如 `node_id` vs `category_id`），在 `providers.py` 里加一个 `SIFProvider.call()` 的参数适配层：

```python
class SIFProvider(Provider):
    def call(self, canonical, args):
        if canonical == "category_products":
            args = {"category_id": args.pop("node_id"), **args}
        return super().call(canonical, args)
```

不要把 Sorftime 的参数硬编码到 `fetch.py`。

## 5. 如果 SIF 只有插件 / CSV 导出

当前 v1.0 **只支持 MCP**，不直接读 SIF 插件导出的 Excel。

如果 SIF 没有 MCP、只有插件导出：

1. 先按 `reference/data-contract.md` 把 Top100 + 类目趋势 + 关键词整理成 raw 文件；
2. 用 `normalize.py` 生成 `data.json`；
3. 继续 `build + verify`。

这条路需要人工映射字段，不如 MCP 稳；适合 SIF 导出质量高、但 MCP 不可用的场景。

## 6. 安全

- key 只放 `.env`；`.env` 不提交。
- `doctor` 只输出工具名，不输出 key。
- `data/` 下的 raw 可能很大；`.gitignore` 默认忽略 `data/*/raw/`，需要归档时再手动加。
