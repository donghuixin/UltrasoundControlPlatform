// Mechanical Markdown -> offline HTML renderer. No network or executable page scripts.
// node scripts/render_usb_handoff.mjs /path/to/marked/lib/marked.esm.js
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const source = path.join(root, 'docs/USB_WINDOWS_INTERFACE_HANDOFF.md');
const output = path.join(root, 'docs/USB_WINDOWS_INTERFACE_HANDOFF.html');
const { marked } = process.argv[2] ? await import(pathToFileURL(path.resolve(process.argv[2]))) : await import('marked');
let content = marked.parse(fs.readFileSync(source, 'utf8'), { gfm: true });
const headings = [];
content = content.replace(/<h([123])>([\s\S]*?)<\/h\1>/g, (_, level, label) => {
  const id = `section-${headings.length + 1}`;
  headings.push({ level: Number(level), label: label.replace(/<[^>]+>/g, ''), id });
  return `<h${level} id="${id}">${label}</h${level}>`;
}).replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, '</table></div>');
const toc = headings.filter(h => h.level === 2).map(h => `<li><a href="#${h.id}">${h.label}</a></li>`).join('\n');
const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FPGA四探头发射板 · Windows USB接口交接</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f2f5f8;color:#182532;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1100px;margin:32px auto;padding:48px 56px;background:white;border-top:6px solid #167c80;box-shadow:0 8px 28px #1231}
.eyebrow{font-size:12px;letter-spacing:2px;color:#167c80;font-weight:700}h1{font-size:30px;line-height:1.4;margin:10px 0 22px}h2{font-size:23px;margin:40px 0 18px;border-bottom:1px solid #dce5ea;padding-bottom:10px}h3{font-size:18px;margin-top:28px}
p,li{overflow-wrap:anywhere}a{color:#116b9b;text-underline-offset:3px}code{font:14px/1.65 Consolas,"Cascadia Code",monospace;background:#eef3f5;padding:2px 4px;border-radius:3px}pre{padding:18px;background:#172937;color:#ecf4fa;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:6px}pre code{background:transparent;padding:0;color:inherit}
.table-wrap{overflow-x:auto;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px 12px;border:1px solid #d5e0e6;text-align:left;vertical-align:top}th{background:#e9f2f3}td code{white-space:normal;overflow-wrap:anywhere}tr:nth-child(even){background:#f8fafb}
nav{background:#edf5f5;border-left:4px solid #167c80;padding:16px 22px;margin:24px 0 34px}nav ul{columns:2;margin:10px 0;padding-left:20px}nav li{break-inside:avoid;font-size:14px}.note{color:#526775;font-size:13px}strong{font-weight:650}blockquote{border-left:3px solid #b4c6d0;margin-left:0;padding-left:18px}
@media(max-width:760px){main{margin:0;padding:24px 18px}h1{font-size:25px}nav ul{columns:1}th,td{padding:8px}}
@media print{body{background:white}main{margin:0;max-width:none;padding:0;border:0;box-shadow:none}h2,h3{break-after:avoid}tr,pre{break-inside:avoid}nav{display:none}a{color:inherit}.table-wrap{overflow:visible}}
</style></head><body><main><div class="eyebrow">HV7350 · TANG PRIMER 25K · PROTOCOL HANDOFF</div>
<p class="note">离线可读 · 文档版本1.1 · 连续发射版 · 2026-09-11 · USB仅控制发射，不传ADC数据</p>
<nav aria-label="文档目录"><strong>开发交接目录</strong><ul>${toc}</ul></nav>
${content}<p class="note">此HTML由同目录Markdown机械生成；接口变更时应同时更新源码、向量、客户端和本文。</p>
</main></body></html>`;
if (/<script\b/i.test(html)) throw new Error('Unexpected executable script in offline handoff');
fs.writeFileSync(output, html);
console.log(`Rendered ${headings.length} headings to ${output}`);
