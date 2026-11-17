# 跨境 AI 工作台 · 技能库

这个仓库只放技能内容，不含代码、不含运行时。技能就是给模型的「岗位说明书」，一个文件夹一个技能。

**先看 [`目录.md`](目录.md)**：有哪些类别、每个类别下有哪些技能、哪些已经重写过了。

工作台（[ecom-workbench](https://github.com/bfsu1666935342-pixel/ecom-workbench)）启动时会读这里的技能；打包发布时会把这里的内容快照进压缩包。

## 目录约定

```
ecom-skills/
├─ listing-writer/
│  ├─ SKILL.md      # 必填：给模型看的正文（frontmatter + 说明）
│  └─ skill.json    # 建议填：给界面看的标题、分组、排序、常用问法、表单字段
├─ ad-diagnose/
├─ keyword-strategy/
└─ …
```

- 文件夹名就是技能 id，用英文小写 + 短横线。
- `skill.json` 里的 `id`、`title`、`group`、`order` 决定界面怎么排；`order` 越小越靠上。
- `SKILL.md` 的正文会被完整拼进系统提示词，长度建议 1500–3000 字。

字段说明和写法规范见工作台仓库的 [`docs/如何添加技能.md`](https://github.com/bfsu1666935342-pixel/ecom-workbench/blob/main/docs/%E5%A6%82%E4%BD%95%E6%B7%BB%E5%8A%A0%E6%8A%80%E8%83%BD.md)。

## 怎么被工作台读到

工作台的 `config.json` 里有这一行：

```json
{
  "extraSkillsDirs": ["../ecom-skills"]
}
```

含义：除了工作台自带的 `skills/`，再读 `../ecom-skills`；**同一个 id 以这里为准**（后面的目录覆盖前面的）。

所以本地开发时把仓库 clone 到工作台文件夹旁边就行：

```
某个目录/
├─ ecom-workbench/
└─ ecom-skills/          ← 这个仓库
```

改完存盘，工作台窗口会打印 `[时间] 技能已重载：N 个`，浏览器按 F5 就是新内容，不用重启、不用打包。

## 迁移状态

工作台自带的 14 个技能是旧版（比较初级）。这里的副本一开始和它一样，之后逐个重写：

1. 在这个仓库重写 `xxx/SKILL.md`；
2. 工作台自动优先读这里的版本；
3. 14 个全部重写完，再把工作台仓库里的 `skills/` 清空。

在全部重写完成之前，两个地方同时存在同名技能是正常的，**改的时候只改这个仓库**。

## 想让技能真的「能干活」

只写"用卖家精灵查一下"不够——模型不知道该调哪个工具，会拿记忆里的数字糊一个答案。技能正文里要写死：

- **工具全名**：`mcp__sorftime__category_report` 这种，和数据源「测试」页显示的一致；
- **传什么参数**：站点、类目、关键词、时间范围；
- **拿到结果怎么校验**：条数够不够、字段是不是空；
- **查不到怎么降级**：停下来问用户要文件，还是换内置的 `web_search`。

内置工具可以直接写：`web_search`、`read_url`、`read_file`、`list_files`、`write_file`、`run_javascript`。

## 和 DSH 的技能格式兼容

`SKILL.md` 用的是标准 frontmatter（`name` + `description`），整个文件夹直接放进 DSH 的 skills 目录也能被识别：

```
<DSH 数据目录>\skills\listing-writer\
```

`skill.json` 只影响工作台的界面，DSH 会忽略它。

## 新增一个技能

1. 建文件夹 `my-skill/`；
2. 放 `SKILL.md`（frontmatter 里写 `name` 和 `description`）；
3. 放 `skill.json`（`id`、`title`、`group`、`order`、`tagline`、`starters`）；
4. 存盘 → 工作台 F5 → 技能库最后多一个。
