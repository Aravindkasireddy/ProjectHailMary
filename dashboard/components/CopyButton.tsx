'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

interface CopyButtonProps {
  text: string;
}

export default function CopyButton({ text }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      onClick={handleCopy}
      type="button"
      className="p-1 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors flex items-center"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="w-3.5 h-3.5 text-emerald-400 animate-in zoom-in-50 duration-150" />
      ) : (
        <Copy className="w-3.5 h-3.5" />
      )}
    </button>
  );
}
