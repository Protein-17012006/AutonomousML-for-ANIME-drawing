export interface FirebaseConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  storageBucket: string;
  messagingSenderId: string;
  appId: string;
}

export interface Message {
  id: string;
  text: string;
  sender: "user" | "ai";
  timestamp: string;
  ai: AIProvider;
  userId?: string;
  chatId: string;
}
export interface Chat {
  id: string;
  title: string;
  userId: string;
  createAt: string;
  updateAt: string;
  aiProvider: AIProvider;
  messageCount: number;
  lastMessage?: string;
  isAnonymous?: boolean;
}

export type AIProvider = "gemini";
