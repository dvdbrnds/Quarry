/* BirdDog logo explorations — now using the real greyhound silhouette.
   All marks share: institutional navy + brass palette, geometric sans wordmark. */

const Greyhound = ({ height = 90, color = 'navy', flip = false }) => {
  const src = {
    navy: 'greyhound-navy.png',
    brass: 'greyhound-brass.png',
    bone: 'greyhound-bone.png',
    brassDeep: 'greyhound-brass-deep.png',
  }[color] || 'greyhound-navy.png';
  return (
    <img src={src} alt="BirdDog greyhound" style={{
      height, width: 'auto', display: 'block',
      transform: flip ? 'scaleX(-1)' : 'none',
    }} />
  );
};

const ChevronMark = ({ size = 80, color = '#0f1d3a' }) => (
  <svg width={size} height={size * 0.7} viewBox="0 0 100 70" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 50 L 40 20 L 50 30 L 60 20 L 90 50" stroke={color} strokeWidth="6" strokeLinejoin="miter" strokeLinecap="square" fill="none" />
    <path d="M30 60 L 50 40 L 70 60" stroke={color} strokeWidth="4" strokeLinejoin="miter" strokeLinecap="square" fill="none" opacity="0.55" />
  </svg>
);

// 01 Stacked Crest
const Direction1Crest = ({ bg = '#0a1428', fg = '#fafaf6', accent = '#fbbf24' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14, padding: 32 }}>
    <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.32em', color: accent, textTransform: 'uppercase' }}>Est · 2026</div>
    <div style={{ width: 220, height: 1, background: accent, opacity: 0.5 }} />
    <Greyhound height={110} color="bone" />
    <div style={{ width: 220, height: 1, background: accent, opacity: 0.5 }} />
    <div style={{ fontFamily: 'var(--bd-display)', fontSize: 38, fontWeight: 700, color: fg, letterSpacing: '-0.02em', lineHeight: 1 }}>
      Bird<span style={{ color: accent }}>Dog</span>
    </div>
    <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 8, letterSpacing: '0.4em', color: fg, opacity: 0.6, textTransform: 'uppercase' }}>Parking Enforcement</div>
  </div>
);

// 02 Horizontal Lockup
const Direction2Horizontal = ({ bg = '#0a1428', fg = '#fafaf6', accent = '#fbbf24' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 40 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
      <div style={{ width: 96, height: 72, background: accent, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, padding: 8 }}>
        <Greyhound height={52} color="navy" />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 700, color: fg, letterSpacing: '-0.025em', lineHeight: 1 }}>BirdDog</div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.28em', color: accent, textTransform: 'uppercase' }}>ALPR · Patrol Suite</div>
      </div>
    </div>
  </div>
);

// 03 License Plate Frame
const Direction3Plate = ({ bg = '#0a1428', fg = '#fafaf6', accent = '#fbbf24' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 32, gap: 20 }}>
    <Greyhound height={100} color="brass" />
    <div style={{
      border: `3px solid ${fg}`, padding: '14px 28px', borderRadius: 8, position: 'relative',
      background: `linear-gradient(180deg, ${fg} 0%, #f3f1ea 100%)`,
    }}>
      <div style={{ position: 'absolute', top: 4, left: '50%', transform: 'translateX(-50%)', fontFamily: 'var(--bd-mono)', fontSize: 7, letterSpacing: '0.3em', color: bg, opacity: 0.7 }}>MORAVIAN UNIVERSITY</div>
      <div style={{ fontFamily: 'var(--bd-display)', fontSize: 44, fontWeight: 800, color: bg, letterSpacing: '0.02em', lineHeight: 1, marginTop: 8 }}>BIRDDOG</div>
      <div style={{ position: 'absolute', bottom: 4, left: '50%', transform: 'translateX(-50%)', fontFamily: 'var(--bd-mono)', fontSize: 7, letterSpacing: '0.3em', color: bg, opacity: 0.7 }}>PARKING · 2026</div>
    </div>
  </div>
);

// 04 Department Shield (greyhound inside)
const Direction4Shield = ({ bg = '#fafaf6', fg = '#0a1428', accent = '#ca8a04' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 32, position: 'relative' }}>
    <svg width="200" height="220" viewBox="0 0 200 220" fill="none" style={{ position: 'absolute' }}>
      <path d="M100 8 L 188 32 L 188 110 C 188 158, 154 196, 100 212 C 46 196, 12 158, 12 110 L 12 32 Z" fill={fg} />
      <path d="M100 18 L 178 38 L 178 110 C 178 152, 148 186, 100 200 C 52 186, 22 152, 22 110 L 22 38 Z" fill="none" stroke={accent} strokeWidth="2" />
      <rect x="40" y="40" width="120" height="22" fill={accent} />
      <text x="100" y="56" fontFamily="var(--bd-mono)" fontSize="10" letterSpacing="0.25em" textAnchor="middle" fill={fg} fontWeight="700">BIRDDOG</text>
      <text x="100" y="186" fontFamily="var(--bd-mono)" fontSize="7" letterSpacing="0.32em" textAnchor="middle" fill={accent}>PATROL · ENFORCE</text>
    </svg>
    <div style={{ position: 'absolute', top: 116, left: '50%', transform: 'translateX(-50%)' }}>
      <Greyhound height={56} color="bone" />
    </div>
  </div>
);

// 05 Scan-line Wordmark
const Direction5Scanline = ({ bg = '#0a1428', fg = '#fafaf6', accent = '#fbbf24' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 32, gap: 24 }}>
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <div style={{ fontFamily: 'var(--bd-display)', fontSize: 56, fontWeight: 800, color: fg, letterSpacing: '-0.04em', lineHeight: 0.9 }}>BirdDog</div>
      <div style={{ position: 'absolute', top: '50%', left: -16, right: -16, height: 2, background: accent, transform: 'translateY(-50%)', opacity: 0.9 }} />
      <div style={{ position: 'absolute', top: '50%', left: -16, height: 8, width: 2, background: accent, transform: 'translateY(-50%)' }} />
      <div style={{ position: 'absolute', top: '50%', right: -16, height: 8, width: 2, background: accent, transform: 'translateY(-50%)' }} />
    </div>
    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
      <Greyhound height={36} color="brass" />
      <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.32em', color: fg, opacity: 0.7, textTransform: 'uppercase' }}>License Plate Recognition</div>
    </div>
  </div>
);

// 06 Greyhound on Brass Tile (replaces BD-only monogram with actual mark)
const Direction6Monogram = ({ bg = '#0a1428', fg = '#fafaf6', accent = '#fbbf24' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 32, gap: 20 }}>
    <div style={{
      width: 200, height: 200, background: accent, borderRadius: 28,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 22,
    }}>
      <Greyhound height={120} color="navy" />
    </div>
    <div style={{ fontFamily: 'var(--bd-display)', fontSize: 28, fontWeight: 700, color: fg, letterSpacing: '-0.02em' }}>BirdDog</div>
  </div>
);

// 07 Department Seal — greyhound at center
const Direction7Seal = ({ bg = '#fafaf6', fg = '#0a1428', accent = '#ca8a04' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 32, position: 'relative' }}>
    <svg width="280" height="280" viewBox="0 0 280 280" fill="none" style={{ position: 'absolute' }}>
      <circle cx="140" cy="140" r="135" fill={fg} />
      <circle cx="140" cy="140" r="120" fill="none" stroke={accent} strokeWidth="1.5" />
      <circle cx="140" cy="140" r="92" fill="none" stroke={accent} strokeWidth="1" />
      <defs>
        <path id="seal-top-r" d="M 40 140 A 100 100 0 0 1 240 140" fill="none" />
        <path id="seal-bot-r" d="M 40 140 A 100 100 0 0 0 240 140" fill="none" />
      </defs>
      <text fontFamily="var(--bd-mono)" fontSize="11" letterSpacing="0.28em" fill="#fafaf6" fontWeight="600">
        <textPath href="#seal-top-r" startOffset="50%" textAnchor="middle">BIRDDOG · PATROL SUITE</textPath>
      </text>
      <text fontFamily="var(--bd-mono)" fontSize="10" letterSpacing="0.28em" fill={accent} fontWeight="600">
        <textPath href="#seal-bot-r" startOffset="50%" textAnchor="middle">EST · 2026 · MORAVIAN</textPath>
      </text>
      <text x="32" y="148" fontSize="14" fill={accent}>★</text>
      <text x="240" y="148" fontSize="14" fill={accent}>★</text>
    </svg>
    <div style={{ position: 'absolute' }}>
      <Greyhound height={80} color="brass" />
    </div>
  </div>
);

// 08 Minimal Type
const Direction8MinimalType = ({ bg = '#fafaf6', fg = '#0a1428', accent = '#ca8a04' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 40, gap: 18 }}>
    <Greyhound height={110} color="navy" />
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 0 }}>
      <div style={{ fontFamily: 'var(--bd-display)', fontSize: 52, fontWeight: 800, color: fg, letterSpacing: '-0.04em', lineHeight: 1 }}>Bird</div>
      <div style={{ fontFamily: 'var(--bd-display)', fontSize: 52, fontWeight: 300, color: fg, letterSpacing: '-0.03em', lineHeight: 1, fontStyle: 'italic' }}>Dog</div>
      <div style={{ width: 8, height: 8, background: accent, borderRadius: '50%', marginLeft: 4 }} />
    </div>
    <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.34em', color: fg, opacity: 0.6, textTransform: 'uppercase' }}>Campus · Patrol · Suite</div>
  </div>
);

// 09 Plate Strip Industrial
const Direction9Strip = ({ bg = '#0a1428', fg = '#fafaf6', accent = '#fbbf24' }) => (
  <div style={{ width: 360, height: 360, background: bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 32 }}>
    <div style={{ display: 'flex', flexDirection: 'column', width: 280, border: `2px solid ${fg}`, borderRadius: 4, overflow: 'hidden' }}>
      <div style={{ background: accent, padding: '6px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontFamily: 'var(--bd-mono)', fontSize: 8, letterSpacing: '0.3em', color: bg, fontWeight: 700 }}>BD-001</span>
        <span style={{ fontFamily: 'var(--bd-mono)', fontSize: 8, letterSpacing: '0.3em', color: bg, fontWeight: 700 }}>v2.0</span>
      </div>
      <div style={{ background: fg, padding: '20px 16px', display: 'flex', alignItems: 'center', gap: 16 }}>
        <Greyhound height={50} color="navy" />
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 800, color: bg, letterSpacing: '-0.03em', lineHeight: 0.95 }}>BirdDog</div>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 8, letterSpacing: '0.28em', color: bg, opacity: 0.7, marginTop: 2 }}>PATROL SUITE</div>
        </div>
      </div>
      <div style={{ background: bg, padding: '6px 12px', borderTop: `1px solid ${fg}`, display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--bd-mono)', fontSize: 7, letterSpacing: '0.3em', color: fg, opacity: 0.6 }}>MORAVIAN UNIVERSITY</span>
        <span style={{ fontFamily: 'var(--bd-mono)', fontSize: 7, letterSpacing: '0.3em', color: accent }}>● ACTIVE</span>
      </div>
    </div>
  </div>
);

Object.assign(window, {
  Greyhound, ChevronMark,
  Direction1Crest, Direction2Horizontal, Direction3Plate, Direction4Shield,
  Direction5Scanline, Direction6Monogram, Direction7Seal, Direction8MinimalType, Direction9Strip,
});
