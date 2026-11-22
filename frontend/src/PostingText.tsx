import Markdown from "react-markdown";

export function PostingText({text}: {text: string}) {
  return <div className="posting-body"><Markdown skipHtml components={{
    img: () => null,
    a: ({href, children}) => href && /^https?:\/\//i.test(href)
      ? <a href={href} target="_blank" rel="noreferrer">{children}</a> : <>{children}</>,
  }}>{text}</Markdown></div>;
}
