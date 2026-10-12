import Markdown, { type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";

// Only recognize explicit Markdown label formatting; never extract or rewrite prose/data.
function hasFactLabel(node: ExtraProps["node"]): boolean {
  const first = node?.children[0];
  if (first?.type === "element" && first.tagName === "p") {
    return hasFactLabel(first);
  }
  if (first?.type !== "element" || first.tagName !== "strong") return false;
  const label = first.children.map(child => child.type === "text" ? child.value : "").join("");
  const next = node?.children[1];
  return label.trimEnd().endsWith(":") ||
    (next?.type === "text" && /^\s*:/.test(next.value));
}

export function AnalystAnswer({ answer }: { answer: string }) {
  return (
    <div className="answer-text answer-markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ node: _node, ...props }) => <h2 className="answer-headline" {...props} />,
          p: ({ node, ...props }) => <p className={hasFactLabel(node) ? "answer-fact" : undefined} {...props} />,
          li: ({ node, ...props }) => <li className={hasFactLabel(node) ? "answer-fact" : undefined} {...props} />,
          table: ({ node: _node, ...props }) => <div className="answer-table"><table {...props} /></div>,
          // Do not fetch external images embedded in untrusted model output.
          img: ({ alt }) => <span>{alt}</span>,
        }}
      >
        {answer}
      </Markdown>
    </div>
  );
}
