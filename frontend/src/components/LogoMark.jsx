/**
 * the spotter mark, straight from the brand files (logo.png): a horizontal
 * teal/coral lockup on a transparent background. rendered as an <img> so it
 * swaps in exactly as designed.
 */
import logo from "../assets/logo.png";

export default function LogoMark({ height = 26 }) {
  return (
    <img
      src={logo}
      alt="Spotter"
      height={height}
      className="logomark-img"
      decoding="async"
      draggable={false}
    />
  );
}