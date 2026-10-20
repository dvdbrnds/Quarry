/**
 * Returns an image src rotated clockwise by `degrees`, baked into the pixels so print
 * layouts get the right width/height. Falls back to the original src if loading fails.
 */
export function rotatedPhotoSrc(src: string, degrees: number): Promise<string> {
  if (!degrees) return Promise.resolve(src);
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const sideways = degrees === 90 || degrees === 270;
        const canvas = document.createElement("canvas");
        canvas.width = sideways ? img.naturalHeight : img.naturalWidth;
        canvas.height = sideways ? img.naturalWidth : img.naturalHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx) return resolve(src);
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.rotate((degrees * Math.PI) / 180);
        ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
        resolve(canvas.toDataURL("image/jpeg", 0.9));
      } catch {
        resolve(src);
      }
    };
    img.onerror = () => resolve(src);
    img.src = src;
  });
}
