---
name: review-to-qa
description: "把 Alexa / Rufus 的买家抱怨、或者差评里提到的缺点，逐条拆成 6 组针对性问答（中文一页、英文一页），导出两 sheet 的 Excel。当用户要把差评、评论或 Alexa 总结变成 FAQ / 详情页 Q&A / 客服话术库时使用。不用于写整篇 Listing 文案。"
---

# 缺点转QA（Review → Q&A）

把「买家主要抱怨」里的**每一条缺点**，单独拆成 6 组咬住它的 Q&A，中文一页、英文一页，导出一个两 sheet 的 Excel。

关键在**逐条**：不是一套通用话术套所有缺点，而是每个缺点单独生成、六个问题全部围绕它。

## 什么时候用

| 用 | 不用 |
|---|---|
| Alexa / Rufus 给出了「买家主要抱怨」 | 写完整 Listing 标题五点（用「Listing 撰写」） |
| 有一批差评，想变成 FAQ 或客服话术 | 做差评聚类分析（用「差评洞察」） |
| 想上 Q&A 板块、补详情页顾虑 | 只想知道某个缺点要不要改产品 |

## 输入（三种都能吃）

1. **文本**：Alexa 那段总结（中英文都行）、差评原文、自己整理的缺点清单。
2. **图片**：Alexa 界面截图、评论截图。**直接让用户把图丢进来就行**——工作台会把图片传给模型识别，不需要额外的 OCR 工具、也不需要用户先转文字。识别不清的地方要问，不要猜。
3. **表格 / PDF**：评论导出表、差评报告。用 `read_file` / `readCsv` 读，先确认读到的列。

## 第 1 步 · 解析成缺点清单

Alexa 的格式通常是「分类 + 正面率 + 短横线要点」：

```
Durability (24% positive):
- Some customers report cracking, seams coming undone, and the piston blowing out within six months
Stability (27% positive):
- Customers say the chair gets noisy, arms can loosen after a few months
```

中文同理：

```
耐用性（24% 正面）：
- 有买家反馈六个月内出现开裂、缝线开线、气压棒漏气
```

解析规则：

- 以 `分类（24% positive）:` 或 `分类（24% 正面）：` **结尾**的行 → 小节标题，括号里的百分比是该缺点的**正面率**。
- 以 `-` `•` `*` `·` 开头的行 → 缺点要点。
- 没有小节的裸文本 → 整段当成一条缺点（仍然可以拆）。
- 以 `Overall` / `总结` 开头的收尾句 → 跳过。
- 同一句里塞了多个问题（「开裂、缝线开线、气压棒失效」）→ 问用户要不要拆成三条分别生成。

分类归到这 8 类之一：`耐用性 durability`、`稳固性 stability`、`坐感舒适 comfort`、`性价比 value`、`尺寸 size`、`安装 assembly`、`气味 smell`、`其他 generic`。

## 第 2 步 · 先给用户核对，别直接生成

列一张表让用户确认，**不要跳步**：

| 序号 | 分类 | 抱怨原文 | 正面率 | 生成 |
|---|---|---|---|---|
| 1 | 耐用性 | 六个月内开裂、缝线开线 | 24% | ☑ |

默认勾选规则：

- 正面率 **< 50%** → 默认勾选（负面是主流）。
- 正面率 **> 50%**（比如 `Value for money (57% positive)`）→ **默认不勾**，那是优点不是缺点。
- 没有正面率的，默认勾选。

用户可以让用户改分类、改原文、取消某几条、调整每条生成的组数（默认 6）。

## 第 3 步 · 逐条生成 6 组问答

每条缺点单独生成一次，**不要把所有缺点混在一次里**。规则：

1. **只围绕这一条缺点**。6 个 Q 是同一个问题的不同侧面（手感材质、久坐支撑、会不会变形、透气季节、适合什么体型、怎么用更舒服等），**绝不跑题**到物流、客服、退换、安装、价格、赠品。
2. **Q 像犹豫的买家在问**：口语、具体、带顾虑，15–35 字。不要「该产品是否……」这种书面腔。
3. **A 像卖家在认真解释**：先正面回答，再给原因或使用建议，最后落到让买家放心。每条 60–100 字。
4. **不许断言材质、工艺、结构、参数、认证或检测结果**（如「透气面料」「高密度海绵」「钢架」「双线缝制」「承重 150kg」「TÜV 认证」「8cm 厚」），除非用户给了。可以描述使用感受和用法建议，但不能虚构没被告知的产品构造。
5. 不要「亲」「您好」，不要「我们的产品是最好的」，不要贬低其他品牌。
6. **中英各一版**，英文不是直译，要像美区 Amazon Q&A 里的说法。
7. 数量必须**严格等于**要求值，少一组算不合格。

正面率低于 50% 的，回答要坦诚、别硬洗。

输出结构（内部用，不展示给用户）：

```json
{"qas":[{"q_zh":"","a_zh":"","q_en":"","a_en":""}]}
```

条数不足就补生成，不要凑数糊弄。

## 第 4 步 · 导出 Excel

把下面整段贴进 `run_javascript`，只改最后 `zhRows` / `enRows` 和文件名：

```js
const CRCT=(()=>{const t=new Int32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;t[n]=c}return t})();
function crc32(u8){let c=0xffffffff;for(let i=0;i<u8.length;i++)c=CRCT[(c^u8[i])&0xff]^(c>>>8);return (c^0xffffffff)>>>0}
const u8=s=>new TextEncoder().encode(s);
function zipStore(files){const now=new Date();const dt=((now.getHours()<<11)|(now.getMinutes()<<5)|(now.getSeconds()>>1))&0xffff;const dd=(((now.getFullYear()-1980)<<9)|((now.getMonth()+1)<<5)|now.getDate())&0xffff;const parts=[],cen=[];let off=0;
for(const f of files){const nb=u8(f.name),d=f.data,crc=crc32(d);const lh=new Uint8Array(30+nb.length),dv=new DataView(lh.buffer);
dv.setUint32(0,0x04034b50,true);dv.setUint16(4,20,true);dv.setUint16(6,0x0800,true);dv.setUint16(8,0,true);dv.setUint16(10,dt,true);dv.setUint16(12,dd,true);dv.setUint32(14,crc,true);dv.setUint32(18,d.length,true);dv.setUint32(22,d.length,true);dv.setUint16(26,nb.length,true);dv.setUint16(28,0,true);lh.set(nb,30);parts.push(lh,d);
const ch=new Uint8Array(46+nb.length),cv=new DataView(ch.buffer);cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(8,0x0800,true);cv.setUint16(10,0,true);cv.setUint16(12,dt,true);cv.setUint16(14,dd,true);cv.setUint32(16,crc,true);cv.setUint32(20,d.length,true);cv.setUint32(24,d.length,true);cv.setUint16(28,nb.length,true);cv.setUint32(42,off,true);ch.set(nb,46);cen.push(ch);off+=lh.length+d.length}
const cd=cen.reduce((a,b)=>a+b.length,0);const eo=new Uint8Array(22),ev=new DataView(eo.buffer);ev.setUint32(0,0x06054b50,true);ev.setUint16(8,files.length,true);ev.setUint16(10,files.length,true);ev.setUint32(12,cd,true);ev.setUint32(16,off,true);
const buf=new Uint8Array(off+cd+22);let p=0;for(const x of parts){buf.set(x,p);p+=x.length}for(const x of cen){buf.set(x,p);p+=x.length}buf.set(eo,p);return buf}
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g,'');
function col(n){let s='';while(n>0){const m=(n-1)%26;s=String.fromCharCode(65+m)+s;n=Math.floor((n-1)/26)}return s}
const STY='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><color rgb="FF1F2937"/><name val="微软雅黑"/><charset val="134"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="微软雅黑"/><charset val="134"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F3864"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFD6DEE8"/></left><right style="thin"><color rgb="FFD6DEE8"/></right><top style="thin"><color rgb="FFD6DEE8"/></top><bottom style="thin"><color rgb="FFD6DEE8"/></bottom><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1" indent="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
function sheetXml(cols,rows,center){const colsXml=cols.map((w,i)=>'<col min="'+(i+1)+'" max="'+(i+1)+'" width="'+w+'" customWidth="1"/>').join('');let body='';
rows.forEach((row,ri)=>{let cells='';row.forEach((v,ci)=>{const s=ri===0?1:(center.indexOf(ci)>=0?3:2);cells+='<c r="'+col(ci+1)+(ri+1)+'" s="'+s+'" t="inlineStr"><is><t xml:space="preserve">'+esc(v)+'</t></is></c>'});body+='<row r="'+(ri+1)+'">'+cells+'</row>'});
const last=col(cols.length)+Math.max(1,rows.length);
return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:'+last+'"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/><cols>'+colsXml+'</cols><sheetData>'+body+'</sheetData><autoFilter ref="A1:'+last+'"/><pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>'}
function buildXlsx(sheets){const files=[];let ct='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>';let wbS='',wbR='',i=0;
for(const sh of sheets){i++;files.push({name:'xl/worksheets/sheet'+i+'.xml',data:u8(sheetXml(sh.cols,sh.rows,sh.center||[]))});ct+='<Override PartName="/xl/worksheets/sheet'+i+'.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>';wbS+='<sheet name="'+esc(sh.name)+'" sheetId="'+i+'" r:id="rId'+i+'"/>';wbR+='<Relationship Id="rId'+i+'" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet'+i+'.xml"/>'}
ct+='<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>';wbR+='<Relationship Id="rId'+(i+1)+'" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>';
files.unshift({name:'[Content_Types].xml',data:u8(ct)});
files.unshift({name:'_rels/.rels',data:u8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')});
files.push({name:'xl/workbook.xml',data:u8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+wbS+'</sheets></workbook>')});
files.push({name:'xl/_rels/workbook.xml.rels',data:u8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+wbR+'</Relationships>')});
files.push({name:'xl/styles.xml',data:u8(STY)});return zipStore(files)}

const zhRows=[['序号','缺点分类','问题 Q','回答 A'],['1','耐用性','坐垫是不是很硬？','初坐会偏挺括，是为了稳定支撑……']];
const enRows=[['No.','Category','Question','Answer'],['1','Durability','Is the cushion too firm?','It starts firm by design……']];
const OUT='reports/产品名-缺点问答-20261117.xlsx';
fs.writeFileSync(OUT,Buffer.from(buildXlsx([
  {name:'中文问答',cols:[6,14,40,56],rows:zhRows,center:[0,1]},
  {name:'English',cols:[6,14,40,56],rows:enRows,center:[0,1]},
])));
console.log('已生成 '+OUT);
```

`zhRows` / `enRows` 第一行必须是表头，之后每行一条问答。导出的文件名按 `产品名-缺点问答-YYYYMMDD.xlsx` 放在 `reports/` 下。

生成完在对话里给一段摘要（几条缺点、共几组、文件路径），**不要**把整张表贴回来。

## 红线

1. **不许编造材质、工艺、结构、参数、认证**。模型不知道真实配置，编了就是 listing 隐患——所以最后一定要提醒用户自己过一遍。
2. 一条缺点只生成围绕它的一组，不许串到其他缺点。
3. Q 不许跑题到物流、客服、退换、安装、价格、赠品。
4. 图片看不清就问，不要猜。
5. 正面率 > 50% 的不默认生成（那是优点）。
6. 条数不足要补，不许拿废话凑到 6 条。
