// The setbacks a plot of this size takes when none are typed. The server applies the same table.
export const autoSetbacks = (area, front, rear, side, shortSide = null) => {
  const row = shortSide != null && shortSide <= 7.0;       // a row-house plot shares its side walls
  const t = row ? (area < 60 ? [1.2, 0.8, 0.0] : [1.5, 1.0, 0.0])
    : area < 60 ? [1.0, 0.8, 0.6] : area < 150 ? [1.5, 1.0, 0.9] : area < 300 ? [2.0, 1.2, 1.0] : [2.5, 1.5, 1.2];
  return [front ?? t[0], rear ?? t[1], side ?? t[2]];
};
