import { useState, useEffect, useRef } from "react";
import { motion } from "motion/react";
import { Send, Plus } from "lucide-react";
import { CricketBall } from "../components/common/CricketBall";
import { RadialGauge } from "../components/common/RadialGauge";
import { CHAT_HISTORY } from "../data/chat";

export function AssistantPage() {
  const [messages, setMessages] = useState(CHAT_HISTORY);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const endRef = useRef<HTMLDivElement>(null!);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, typing]);

  const send = () => {
    if (!input.trim()) return;
    const userMsg = { id: `u${Date.now()}`, role: "user", text: input, richCard: null };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      setMessages(prev => [...prev, { id: `a${Date.now()}`, role: "assistant", text: "Based on the current data, I can see a strong case for that selection. The form metrics and venue history both support this choice. Would you like me to run a specific matchup analysis or generate the full XI recommendation?", richCard: null }]);
    }, 2000);
  };

  return (
    <div className="flex h-full">
      {/* Conversation list */}
      <div className="w-52 flex-shrink-0 border-r border-border p-3 space-y-1">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Chats</span>
          <button className="p-1 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><Plus size={13} /></button>
        </div>
        {[{ label: "vs Australia analysis", active: true }, { label: "Pitch conditions MCG" }, { label: "Hardik form review" }, { label: "New Zealand preview" }].map((c, i) => (
          <button key={i} className={`w-full text-left px-2.5 py-2 rounded-lg text-[12px] transition-colors truncate ${c.active ? "bg-[#AAFF57]/10 text-[#AAFF57] font-medium" : "text-muted-foreground hover:text-foreground hover:bg-secondary"}`}>
            {c.label}
          </button>
        ))}
      </div>

      {/* Chat thread */}
      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-auto p-5 space-y-4">
          {messages.map((msg, i) => (
            <motion.div key={msg.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i < 4 ? 0 : 0 }}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              {msg.role === "assistant" && (
                <div className="w-7 h-7 rounded-full bg-[#AAFF57] flex items-center justify-center mr-2 flex-shrink-0 mt-0.5">
                  <CricketBall size={14} className="text-[#0D0D06]" />
                </div>
              )}
              <div className={`max-w-[75%] ${msg.role === "user" ? "bg-[#AAFF57] text-[#0D0D06]" : "bg-card border border-border text-foreground"} rounded-2xl px-4 py-3 text-sm leading-relaxed`}>
                <p>{msg.text}</p>
                {msg.richCard && msg.richCard.type === "player" && (
                  <div className="mt-3 pt-3 border-t border-border flex items-center gap-3">
                    <div className="w-9 h-9 rounded-full flex items-center justify-center text-[11px] font-bold flex-shrink-0" style={{ backgroundColor: msg.richCard.player.color + "33", color: msg.richCard.player.color }}>{msg.richCard.player.initials}</div>
                    <div className="flex-1">
                      <div className="text-[13px] font-semibold">{msg.richCard.player.name}</div>
                      <div className="text-[10px] opacity-70">{msg.richCard.player.archetype}</div>
                    </div>
                    <RadialGauge value={msg.richCard.player.score} size={40} strokeWidth={3} color={msg.richCard.player.color} />
                  </div>
                )}
              </div>
            </motion.div>
          ))}
          {typing && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-[#AAFF57] flex items-center justify-center flex-shrink-0">
                <CricketBall size={14} className="text-[#0D0D06]" />
              </div>
              <div className="bg-card border border-border rounded-2xl px-4 py-3 flex gap-1">
                {[0, 1, 2].map(d => <div key={d} className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: `${d * 0.15}s` }} />)}
              </div>
            </motion.div>
          )}
          <div ref={endRef} />
        </div>

        {/* Input */}
        <div className="border-t border-border p-4">
          <div className="flex gap-2">
            <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && send()}
              placeholder="Ask about player form, matchups, selection strategy…"
              className="flex-1 text-sm bg-secondary border border-border rounded-xl px-4 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40" />
            <button onClick={send} className="p-2.5 bg-[#AAFF57] text-[#0D0D06] rounded-xl hover:opacity-90 transition-opacity">
              <Send size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
