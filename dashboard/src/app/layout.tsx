import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import "../styles/design.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MAAS Sourcing Agent",
  description: "DevOps/SRE job sourcing, classification, and application pipeline.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {/* Particle canvas background */}
        <canvas id="aria-canvas" aria-hidden="true" />

        {/* Page content */}
        {children}

        {/* ARIA Floating Companion Widget */}
        <div id="aria-widget">
          <div id="aria-bubble">
            <em>17 new targets</em> acquired this cycle.<br />
            Mission confidence avg: <em>86%</em>. Standing by, Commander.
          </div>
          <div id="aria-float" title="ARIA — Click to interact">
            <div className="aria-float-pulse" />
            {/* ARIA SVG Mascot */}
            <svg width="68" height="68" viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg" aria-label="ARIA mascot">
              <defs>
                <radialGradient id="al-fg" cx="50%" cy="40%" r="60%">
                  <stop offset="0%" stopColor="#1A1060"/>
                  <stop offset="100%" stopColor="#080420"/>
                </radialGradient>
                <linearGradient id="al-hg" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#7B2FBE"/>
                  <stop offset="100%" stopColor="#1A3DAF"/>
                </linearGradient>
                <filter id="al-gc">
                  <feGaussianBlur stdDeviation="2" result="b"/>
                  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
                <filter id="al-gv">
                  <feGaussianBlur stdDeviation="1.5" result="b"/>
                  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
              </defs>
              {/* Outer ring */}
              <circle cx="40" cy="40" r="38" fill="#050714" stroke="#00F0FF" strokeWidth="1.2" filter="url(#al-gc)"/>
              <circle cx="40" cy="40" r="36" fill="#050714"/>
              {/* Hair */}
              <path d="M18 42 Q14 28 20 16 Q30 7 40 9 Q50 7 60 16 Q66 28 62 42" fill="url(#al-hg)"/>
              <path d="M18 42 Q11 50 13 60 L22 54 Q19 47 21 43Z" fill="#5500A0"/>
              <path d="M62 42 Q69 50 67 60 L58 54 Q61 47 59 43Z" fill="#5500A0"/>
              {/* Face */}
              <ellipse cx="40" cy="45" rx="17" ry="19" fill="url(#al-fg)"/>
              {/* Visor band */}
              <rect x="23" y="36" width="34" height="10" rx="1" fill="#00F0FF" opacity="0.07"/>
              <rect x="23" y="36" width="34" height="1.5" rx="0.5" fill="#00F0FF" opacity="0.55" filter="url(#al-gc)"/>
              {/* Eyes */}
              <ellipse cx="31" cy="41" rx="5.5" ry="6.5" fill="#000B20" stroke="#00F0FF" strokeWidth="0.8"/>
              <ellipse cx="49" cy="41" rx="5.5" ry="6.5" fill="#000B20" stroke="#00F0FF" strokeWidth="0.8"/>
              <ellipse cx="31" cy="41" rx="4" ry="5" fill="#00F0FF" opacity="0.9" filter="url(#al-gc)"/>
              <ellipse cx="49" cy="41" rx="4" ry="5" fill="#00F0FF" opacity="0.9" filter="url(#al-gc)"/>
              <ellipse cx="31" cy="41" rx="2.2" ry="3" fill="#001A30"/>
              <ellipse cx="49" cy="41" rx="2.2" ry="3" fill="#001A30"/>
              <ellipse cx="32.5" cy="38.5" rx="1.4" ry="1.4" fill="white" opacity="0.95"/>
              <ellipse cx="50.5" cy="38.5" rx="1.4" ry="1.4" fill="white" opacity="0.95"/>
              {/* Lashes */}
              <path d="M25.5 36 Q31 34 36.5 36" stroke="#B44FFF" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
              <path d="M43.5 36 Q49 34 54.5 36" stroke="#B44FFF" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
              {/* Nose + Mouth */}
              <path d="M38.5 48 Q40 50.5 41.5 48" stroke="#5040A0" strokeWidth="1.2" fill="none"/>
              <path d="M34 54 Q40 58 46 54" stroke="#B44FFF" strokeWidth="1.8" fill="none" strokeLinecap="round" filter="url(#al-gv)"/>
              {/* Hair strands */}
              <path d="M28 26 Q26 33 28 38" stroke="#6600BB" strokeWidth="3.5" fill="none" strokeLinecap="round"/>
              <path d="M34 24 Q32 31 34 36" stroke="#5500AA" strokeWidth="2.5" fill="none" strokeLinecap="round"/>
              <path d="M52 26 Q54 33 52 38" stroke="#6600BB" strokeWidth="3.5" fill="none" strokeLinecap="round"/>
              {/* Antenna */}
              <line x1="40" y1="9" x2="40" y2="2" stroke="#00F0FF" strokeWidth="1.8" filter="url(#al-gc)"/>
              <circle cx="40" cy="1.5" r="2.8" fill="#00F0FF" filter="url(#al-gc)">
                <animate attributeName="opacity" values="1;0.15;1" dur="1.8s" repeatCount="indefinite"/>
              </circle>
              {/* Cheek circuits */}
              <g opacity="0.6" filter="url(#al-gc)">
                <line x1="22" y1="44" x2="17" y2="44" stroke="#00F0FF" strokeWidth="0.8"/>
                <line x1="17" y1="44" x2="17" y2="39" stroke="#00F0FF" strokeWidth="0.8"/>
                <circle cx="17" cy="39" r="1.2" fill="#00F0FF"/>
              </g>
              <g opacity="0.6" filter="url(#al-gc)">
                <line x1="58" y1="44" x2="63" y2="44" stroke="#00F0FF" strokeWidth="0.8"/>
                <line x1="63" y1="44" x2="63" y2="39" stroke="#00F0FF" strokeWidth="0.8"/>
                <circle cx="63" cy="39" r="1.2" fill="#00F0FF"/>
              </g>
              {/* Collar */}
              <path d="M23 64 L27 68 L40 70 L53 68 L57 64 Q48 66 40 66 Q32 66 23 64Z" fill="#080420" stroke="#B44FFF" strokeWidth="0.9"/>
              <line x1="36" y1="67" x2="44" y2="67" stroke="#00F0FF" strokeWidth="0.8" opacity="0.7"/>
              <circle cx="40" cy="67" r="1.8" fill="#00F0FF" opacity="0.9"/>
            </svg>
          </div>
        </div>

        {/* Particle + ARIA widget script */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
(function(){
  /* ── Particle canvas ── */
  var c = document.getElementById('aria-canvas');
  if (!c) return;
  var ctx = c.getContext('2d');
  var W, H, pts = [];
  function resize(){
    W = c.width = window.innerWidth;
    H = c.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', function(){ resize(); init(); });
  function init(){
    pts = [];
    var n = Math.floor(W * H / 16000);
    for (var i = 0; i < n; i++) pts.push({
      x: Math.random() * W,
      y: Math.random() * H,
      vy: 0.25 + Math.random() * 0.6,
      size: Math.random() < 0.7 ? 0.8 : 1.4,
      op: 0.06 + Math.random() * 0.22,
      col: Math.random() < 0.7 ? '0,240,255' : '180,79,255'
    });
  }
  init();
  function draw(){
    ctx.clearRect(0,0,W,H);
    for (var i = 0; i < pts.length; i++){
      var p = pts[i];
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(' + p.col + ',' + p.op + ')';
      ctx.fill();
      p.y += p.vy;
      if (p.y > H + 4){ p.y = -4; p.x = Math.random() * W; }
    }
    requestAnimationFrame(draw);
  }
  draw();

  /* ── ARIA companion ── */
  var lines = [
    function(){ return 'Pipeline <em>ready</em>. All 5 ATS channels online.<br/>Standing by, Commander.'; },
    function(){ return '<em>472 companies</em> monitored.<br/>Next scrape cycle in <em>14 min</em>.'; },
    function(){ return 'Consulting firms <em>auto-filtered</em>.<br/>Only direct employment targets shown.'; },
    function(){ return 'H1B sponsor data <em>loaded</em>.<br/>Visa-friendly matches highlighted.'; },
  ];
  var idx = 0;
  var bub = document.getElementById('aria-bubble');
  var float = document.getElementById('aria-float');

  function cycleDialogue(){
    idx = (idx + 1) % lines.length;
    if (bub) { bub.style.animation = 'none'; bub.offsetHeight; bub.style.animation = ''; bub.innerHTML = lines[idx](); }
  }

  var bubVisible = true;
  if (float) float.addEventListener('click', function(){
    bubVisible = !bubVisible;
    if (bub) bub.style.display = bubVisible ? 'block' : 'none';
    if (bubVisible) cycleDialogue();
  });

  setInterval(cycleDialogue, 9000);
})();
`,
          }}
        />
      </body>
    </html>
  );
}
