// Tiny, safe Markdown subset renderer (code blocks, inline code, bold, italics, links, lists, headings).
// Produces React elements only — never injects HTML.

function renderInline(text, keyPrefix) {
  const out = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))|(https?:\/\/[^\s)]+)/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${keyPrefix}-${i++}`;
    if (m[1]) out.push(<code key={k}>{m[1].slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k}>{m[2].slice(2, -2)}</strong>);
    else if (m[3]) out.push(<em key={k}>{m[3].slice(1, -1)}</em>);
    else if (m[4]) {
      const label = m[4].slice(1, m[4].indexOf("]"));
      out.push(<a key={k} href={m[5]} target="_blank" rel="noreferrer noopener">{label}</a>);
    } else if (m[6]) out.push(<a key={k} href={m[6]} target="_blank" rel="noreferrer noopener">{m[6]}</a>);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text }) {
  const blocks = [];
  const lines = (text || "").replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3);
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i += 1;
      blocks.push(<pre key={key++} data-lang={lang || undefined}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
        i += 1;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={key++}>{items.map((it, j) => <li key={j}>{renderInline(it, `l${key}-${j}`)}</li>)}</List>);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)/);
    if (heading) {
      blocks.push(<h4 key={key++}>{renderInline(heading[2], `h${key}`)}</h4>);
      i += 1;
      continue;
    }
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i]) && !lines[i].trim().startsWith("```") && !/^#{1,4}\s/.test(lines[i])) {
      para.push(lines[i++]);
    }
    blocks.push(<p key={key++}>{renderInline(para.join("\n"), `p${key}`)}</p>);
  }
  return <div className="markdown">{blocks}</div>;
}
