/**
 * the spotter mark: three dots (coral / teal / pale mint) + the lowercase
 * wordmark. drawn inline so it's crisp at any size and pulls the exact
 * brand colors — no raster, no unknown-bg png to fight.
 */
export default function LogoMark({ wordmark = true, size = 20 }) {
  const gap = size * 0.45;
  const total = size * 3 + gap * 2;
  const colors = ["#f84960", "#008080", "#bcddde"];
  return (
    <span className="logomark">
      <svg
        width={total}
        height={size}
        viewBox={`0 0 ${total} ${size}`}
        aria-hidden="true"
      >
        {colors.map((c, i) => (
          <circle
            key={c}
            cx={i * (size + gap) + size / 2}
            cy={size / 2}
            r={size / 2}
            fill={c}
          />
        ))}
      </svg>
      {wordmark && <span className="wordmark">spotter</span>}
    </span>
  );
}