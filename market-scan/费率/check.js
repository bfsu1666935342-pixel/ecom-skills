'use strict';

/* 从 SKILL.md 里抽出内嵌的 FBA 查表代码，跑官方示例验证。
   单一数据源：改 SKILL.md 就够，跑这个脚本能立刻发现抄错。 */
const fs = require('fs');
const path = require('path');

const md = fs.readFileSync(path.join(__dirname, '..', 'SKILL.md'), 'utf8');
const block = (md.match(/```js\n([\s\S]*?)```/) || [])[1];
if (!block) {
  console.log('FAIL 没在 SKILL.md 里找到 js 代码块');
  process.exit(1);
}

const body = block.split(/const r=fba\(/)[0];
let fba;
try {
  fba = new Function(body + '\nreturn { fba, tier };')();
} catch (err) {
  console.log('FAIL 代码块无法执行：' + err.message);
  process.exit(1);
}

// 卖家平台页面自带的 2027 非旺季示例（已人工核对过）
const cases = [
  { n: '移动设备外壳', p: { L: 13.8, W: 9, H: 0.7, lb: 2.88 / 16, price: 8, period: '2027' }, want: 2.72, tier: '小号标准' },
  { n: 'T恤', p: { L: 13, W: 9, H: 0.85, lb: 5.4 / 16, price: 25, period: '2027' }, want: 4.26, tier: '大号标准' },
  { n: '熨斗', p: { L: 12.6, W: 6.6, H: 5.5, lb: 3.35, price: 25, period: '2027' }, want: 7.32, tier: '大号标准' },
  { n: '婴儿床', p: { L: 24, W: 7.5, H: 6, lb: 7.9, price: 80, period: '2027' }, want: 10.24, tier: '小号大件' },
  { n: '显示器', p: { L: 54, W: 34, H: 3.5, lb: 41, price: 40, period: '2027' }, want: 27.1, tier: '小型超大件' },
  { n: '电视机', p: { L: 65, W: 20, H: 7, lb: 62, price: 400, period: '2027' }, want: 36.55, tier: '中型超大件' },
];

let bad = 0;
for (const c of cases) {
  const r = fba.fba(c.p);
  const ok = Math.abs(r.fee - c.want) < 0.011 && r.tier === c.tier;
  if (!ok) bad += 1;
  console.log((ok ? 'ok   ' : 'FAIL ') + c.n.padEnd(12) + r.tier.padEnd(10) + '$' + String(r.fee).padEnd(8) +
    '(期望 $' + c.want + ' / ' + c.tier + ')');
}

// 大件回归
const big = [
  ['电竞椅-旺季', { L: 30, W: 25, H: 12, lb: 40, price: 200, period: '2026peak' }, 50.63, '超大件50-70'],
  ['电竞椅-2027', { L: 30, W: 25, H: 12, lb: 40, price: 200, period: '2027' }, 35.99, '中型超大件'],
  ['沙发-旺季', { L: 70, W: 32, H: 14, lb: 90, price: 400, period: '2026peak' }, 217.71, '超大件150+'],
  ['沙发-2027', { L: 70, W: 32, H: 14, lb: 90, price: 400, period: '2027' }, 205.53, '重型特殊超大件'],
];
for (const [n, p, want, t] of big) {
  const r = fba.fba(p);
  const ok = Math.abs(r.fee - want) < 0.011 && r.tier === t;
  if (!ok) bad += 1;
  console.log((ok ? 'ok   ' : 'FAIL ') + n.padEnd(12) + r.tier.padEnd(10) + '$' + String(r.fee).padEnd(8) +
    '(期望 $' + want + ' / ' + t + ')');
}

console.log('\n' + (bad ? bad + ' 项不符' : '全部通过：代码块与官方示例一致'));
process.exit(bad ? 1 : 0);
