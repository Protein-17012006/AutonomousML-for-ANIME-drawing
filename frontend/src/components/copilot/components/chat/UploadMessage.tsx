import { ChatTextBubble } from "./ChatTextBubble";

export function UploadMessage({ text }: { text: string }) {
  return <ChatTextBubble tone="user">{text}</ChatTextBubble>;
}
