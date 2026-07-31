import { ChatTextBubble } from "./ChatTextBubble";

export function ErrorMessage({ text }: { text: string }) {
  return <ChatTextBubble tone="error">{text}</ChatTextBubble>;
}
