import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

/** Markdown renderer tuned for chat bubbles: compact typography, styled code
 *  blocks / tables / lists, GFM extras (tables, strikethrough, task lists).
 *  Links open in a new tab; code keeps its newlines without extra margins so
 *  bubbles stay dense like a terminal transcript. */
export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("min-w-0 text-sm leading-relaxed break-words", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: (props) => <p className="my-1 first:mt-0 last:mb-0" {...props} />,
          h1: (props) => <h1 className="mt-2 mb-1 text-base font-semibold first:mt-0" {...props} />,
          h2: (props) => <h2 className="mt-2 mb-1 text-sm font-semibold first:mt-0" {...props} />,
          h3: (props) => <h3 className="mt-1.5 mb-0.5 text-sm font-medium first:mt-0" {...props} />,
          ul: (props) => <ul className="my-1 list-disc space-y-0.5 pl-5" {...props} />,
          ol: (props) => <ol className="my-1 list-decimal space-y-0.5 pl-5" {...props} />,
          li: (props) => <li className="marker:text-muted-foreground" {...props} />,
          a: (props) => (
            <a
              className="text-primary underline underline-offset-2 hover:opacity-80"
              target="_blank"
              rel="noreferrer"
              {...props}
            />
          ),
          blockquote: (props) => (
            <blockquote
              className="my-1 border-l-2 border-border pl-2 text-muted-foreground"
              {...props}
            />
          ),
          hr: () => <hr className="my-2 border-border" />,
          table: (props) => (
            <div className="my-1 overflow-x-auto rounded-md border">
              <table className="w-full border-collapse text-xs" {...props} />
            </div>
          ),
          th: (props) => (
            <th className="border-b bg-muted/50 px-2 py-1 text-left font-medium" {...props} />
          ),
          td: (props) => <td className="border-b px-2 py-1 align-top last:border-b-0" {...props} />,
          code: ({ className: cls, children, ...rest }) => {
            const isBlock = /language-/.test(cls ?? "")
            if (isBlock) {
              return (
                <code
                  className={cn("block overflow-x-auto p-2 font-mono text-xs leading-snug", cls)}
                  {...rest}
                >
                  {children}
                </code>
              )
            }
            return (
              <code
                className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"
                {...rest}
              >
                {children}
              </code>
            )
          },
          pre: (props) => (
            <pre
              className="my-1.5 overflow-x-auto rounded-lg bg-muted p-0 [&_code]:bg-transparent"
              {...props}
            />
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
