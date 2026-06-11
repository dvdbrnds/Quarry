/* App icons, splash, login art — using real greyhound silhouette */

const Greyhound = window.Greyhound || (({ height = 90, color = 'navy' }) => {
  const src = { navy: 'greyhound-navy.png', brass: 'greyhound-brass.png', bone: 'greyhound-bone.png', brassDeep: 'greyhound-brass-deep.png' }[color];
  return <img src={src} style={{ height, width: 'auto', display: 'block' }} />;
});

// ============================================================
// APP ICONS
// ============================================================
const AppIconA = () => (
  <div style={{
    width: 200, height: 200, background: '#0a1428', borderRadius: 44,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 12px 32px -8px rgba(10,20,40,0.4)',
    position: 'relative', overflow: 'hidden', padding: 28,
  }}>
    <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(circle at 30% 25%, rgba(251,191,36,0.1), transparent 60%)' }} />
    <Greyhound height={100} color="brass" />
  </div>
);

const AppIconB = () => (
  <div style={{
    width: 200, height: 200, background: '#fbbf24', borderRadius: 44,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 12px 32px -8px rgba(10,20,40,0.4)',
    position: 'relative', overflow: 'hidden', padding: 28,
  }}>
    <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(160deg, rgba(255,255,255,0.2), transparent 50%)' }} />
    <Greyhound height={100} color="navy" />
  </div>
);

const AppIconC = () => (
  // Greyhound + BD wordmark stacked
  <div style={{
    width: 200, height: 200, background: '#0a1428', borderRadius: 44,
    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 12px 32px -8px rgba(10,20,40,0.4)',
    position: 'relative', overflow: 'hidden', padding: 22, gap: 6,
  }}>
    <Greyhound height={80} color="brass" />
    <div style={{ width: 100, height: 1, background: 'rgba(251,191,36,0.4)' }} />
    <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.32em', color: '#fbbf24', fontWeight: 700 }}>BIRDDOG</div>
  </div>
);

const AppIconD = () => (
  <div style={{
    width: 200, height: 200, background: '#f3f1ea', borderRadius: 44,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 12px 32px -8px rgba(10,20,40,0.4)',
    border: '1px solid rgba(10,20,40,0.08)', padding: 28,
  }}>
    <Greyhound height={100} color="navy" />
  </div>
);

// ============================================================
// SPLASH SCREEN
// ============================================================
const SplashScreen = ({ width = 320, height = 692, label = 'iPhone' }) => (
  <div style={{
    width, height, background: '#050b1a', borderRadius: 36,
    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'space-between',
    padding: '60px 24px 40px', position: 'relative', overflow: 'hidden',
  }}>
    <div style={{ position: 'absolute', inset: 0, opacity: 0.06,
      backgroundImage: 'linear-gradient(rgba(251,191,36,1) 1px, transparent 1px), linear-gradient(90deg, rgba(251,191,36,1) 1px, transparent 1px)',
      backgroundSize: '40px 40px',
    }} />
    <div style={{ position: 'absolute', top: '20%', left: '50%', transform: 'translateX(-50%)', width: 320, height: 320, borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(251,191,36,0.12), transparent 60%)', filter: 'blur(40px)' }} />

    <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.34em', color: '#fbbf24', textTransform: 'uppercase', zIndex: 1 }}>{label}</div>

    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 24, zIndex: 1 }}>
      <Greyhound height={width * 0.35} color="brass" />
      <div style={{ width: 140, height: 1, background: 'rgba(251,191,36,0.5)' }} />
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
        <div style={{ fontFamily: 'var(--bd-display)', fontSize: width * 0.13, fontWeight: 800, color: '#fafaf6', letterSpacing: '-0.04em', lineHeight: 1 }}>BirdDog</div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.32em', color: '#fafaf6', opacity: 0.6, textTransform: 'uppercase' }}>Patrol Suite</div>
      </div>
    </div>

    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, zIndex: 1 }}>
      <div style={{ width: 32, height: 2, background: '#fbbf24', borderRadius: 2 }} />
      <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 7, letterSpacing: '0.3em', color: '#fafaf6', opacity: 0.4, textTransform: 'uppercase' }}>Moravian University · Beta</div>
    </div>
  </div>
);

// ============================================================
// LOGIN HEADER ART
// ============================================================
const LoginHeaderArt = () => (
  <div style={{
    width: 720, height: 320, background: '#0a1428', borderRadius: 12,
    position: 'relative', overflow: 'hidden',
  }}>
    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 4, background: '#fbbf24' }} />
    <div style={{ position: 'absolute', top: 12, left: 0, right: 0, height: 1, background: 'rgba(251,191,36,0.4)' }} />
    <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, background: 'rgba(251,191,36,0.3)' }} />
    {[['top',24,'left',24,'M0 0 L 24 0 M 0 0 L 0 24'],
      ['top',24,'right',24,'M24 0 L 0 0 M 24 0 L 24 24'],
      ['bottom',24,'left',24,'M0 24 L 24 24 M 0 24 L 0 0'],
      ['bottom',24,'right',24,'M24 24 L 0 24 M 24 24 L 24 0']].map(([a,b,c,d,p],i) => (
      <svg key={i} style={{ position: 'absolute', [a]: b, [c]: d }} width="24" height="24" viewBox="0 0 24 24" fill="none">
        <path d={p} stroke="#fbbf24" strokeWidth="2" />
      </svg>
    ))}
    <div style={{ position: 'absolute', top: '40%', left: '60%', width: 400, height: 400, borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(251,191,36,0.15), transparent 60%)', filter: 'blur(40px)' }} />
    <div style={{ position: 'absolute', right: 50, top: '50%', transform: 'translateY(-50%)' }}>
      <Greyhound height={210} color="brass" />
    </div>
    <div style={{ position: 'absolute', left: 56, top: 80, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.36em', color: '#fbbf24', textTransform: 'uppercase' }}>Authorized Personnel · Patrol Suite</div>
      <div style={{ fontFamily: 'var(--bd-display)', fontSize: 64, fontWeight: 800, color: '#fafaf6', letterSpacing: '-0.04em', lineHeight: 0.95 }}>BirdDog</div>
      <div style={{ fontFamily: 'var(--bd-body)', fontSize: 14, color: '#fafaf6', opacity: 0.65, maxWidth: 320, lineHeight: 1.4 }}>License plate recognition and parking enforcement for campus patrol.</div>
    </div>
  </div>
);

// ============================================================
// IN-APP HEADER
// ============================================================
const InAppHeader = ({ inverted = false }) => {
  const fg = inverted ? '#fafaf6' : '#0a1428';
  const bg = inverted ? '#0a1428' : '#fafaf6';
  return (
    <div style={{
      width: 360, height: 80, background: bg, borderRadius: 8,
      display: 'flex', alignItems: 'center', gap: 14, padding: '0 24px',
      border: `1px solid ${inverted ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.06)'}`,
    }}>
      <Greyhound height={36} color={inverted ? 'bone' : 'navy'} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <div style={{ fontFamily: 'var(--bd-display)', fontSize: 22, fontWeight: 800, color: fg, letterSpacing: '-0.03em', lineHeight: 1 }}>BirdDog</div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 8, letterSpacing: '0.3em', color: fg, opacity: 0.55, textTransform: 'uppercase' }}>Patrol Suite</div>
      </div>
    </div>
  );
};

// ============================================================
// FAVICON
// ============================================================
const Favicon = ({ size = 64 }) => (
  <div style={{
    width: size, height: size, background: '#0a1428',
    borderRadius: Math.max(2, size * 0.18),
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 4px 12px -4px rgba(10,20,40,0.4)', padding: size * 0.14,
  }}>
    <Greyhound height={size * 0.55} color="brass" />
  </div>
);

Object.assign(window, { AppIconA, AppIconB, AppIconC, AppIconD, SplashScreen, LoginHeaderArt, InAppHeader, Favicon });
