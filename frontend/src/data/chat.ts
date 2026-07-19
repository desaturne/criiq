export interface ChatMessage {
  id: string; role: "user" | "assistant"; text: string;
  richCard: { type: "player"; player: { name: string; initials: string; color: string; archetype: string; score: number } } | null;
}

export const CHAT_HISTORY: ChatMessage[] = [
  { id: "c1", role: "user", text: "Who should I consider for the No.3 spot against Australia at MCG?", richCard: null },
  { id: "c2", role: "assistant", text: "Based on the current form data and historical MCG records, Virat Kohli is the clear choice at No.3. He averages 62 against Australia in his last 8 encounters and handles pace bowling exceptionally well — critical given MCG's 78% pace support index.", richCard: null },
  { id: "c3", role: "user", text: "What about Hardik's recent form? Should I be worried?", richCard: null },
  { id: "c4", role: "assistant", text: "Yes, there are valid concerns. Hardik's economy rate has climbed to 8.14 in his last 3 games, and his full-toss count is elevated. His batting hasn't compensated — only one 20+ score in 5 outings. I'd rate him at 72/100 for this selection, and recommend having Axar Patel as an alternative who offers better economy at this venue.", richCard: null },
];
