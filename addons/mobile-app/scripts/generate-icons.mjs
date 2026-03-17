import sharp from "sharp";
import { mkdirSync, readdirSync, unlinkSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ICONS_DIR = join(__dirname, "..", "public", "icons");
const SPLASH_DIR = join(__dirname, "..", "public", "splash");
const SOURCE = join(ICONS_DIR, "icon-source.png");

mkdirSync(ICONS_DIR, { recursive: true });
mkdirSync(SPLASH_DIR, { recursive: true });

// Clean old generated icons (keep source)
const existing = readdirSync(ICONS_DIR);
for (const file of existing) {
  if (file !== "icon-source.png") {
    unlinkSync(join(ICONS_DIR, file));
    console.log(`  ✗ deleted ${file}`);
  }
}

// Resize source icon to all required sizes
const icons = [
  { name: "icon-192.png", size: 192 },
  { name: "icon-384.png", size: 384 },
  { name: "icon-512.png", size: 512 },
  { name: "apple-touch-icon-120.png", size: 120 },
  { name: "apple-touch-icon-152.png", size: 152 },
  { name: "apple-touch-icon-167.png", size: 167 },
  { name: "apple-touch-icon-180.png", size: 180 },
  { name: "favicon-32.png", size: 32 },
  { name: "favicon-16.png", size: 16 },
];

for (const { name, size } of icons) {
  await sharp(SOURCE)
    .resize(size, size, { fit: "contain", background: { r: 19, g: 23, b: 34, alpha: 1 } })
    .png()
    .toFile(join(ICONS_DIR, name));
  console.log(`  ✓ ${name} (${size}x${size})`);
}

// Maskable icon — add 10% padding around icon for safe zone
const maskableSize = 512;
const innerSize = Math.round(maskableSize * 0.8);
const offset = Math.round((maskableSize - innerSize) / 2);

const resizedForMaskable = await sharp(SOURCE)
  .resize(innerSize, innerSize, { fit: "contain", background: { r: 19, g: 23, b: 34, alpha: 1 } })
  .toBuffer();

await sharp({
  create: {
    width: maskableSize,
    height: maskableSize,
    channels: 4,
    background: { r: 19, g: 23, b: 34, alpha: 255 },
  },
})
  .composite([{ input: resizedForMaskable, left: offset, top: offset }])
  .png()
  .toFile(join(ICONS_DIR, "icon-maskable-512.png"));
console.log(`  ✓ icon-maskable-512.png (${maskableSize}x${maskableSize} maskable)`);

// Apple splash screens — icon centered on #131722 background
const splashDevices = [
  { w: 1170, h: 2532, name: "apple-splash-1170x2532.png" },
  { w: 1179, h: 2556, name: "apple-splash-1179x2556.png" },
  { w: 1290, h: 2796, name: "apple-splash-1290x2796.png" },
  { w: 1320, h: 2868, name: "apple-splash-1320x2868.png" },
  { w: 750, h: 1334, name: "apple-splash-750x1334.png" },
  { w: 1125, h: 2436, name: "apple-splash-1125x2436.png" },
  { w: 1242, h: 2688, name: "apple-splash-1242x2688.png" },
  { w: 828, h: 1792, name: "apple-splash-828x1792.png" },
  { w: 1284, h: 2778, name: "apple-splash-1284x2778.png" },
  { w: 640, h: 1136, name: "apple-splash-640x1136.png" },
];

// Pre-resize icon for splash screens
const splashIconSize = 200;
const splashIcon = await sharp(SOURCE)
  .resize(splashIconSize, splashIconSize, { fit: "contain", background: { r: 19, g: 23, b: 34, alpha: 1 } })
  .toBuffer();

for (const { w, h, name } of splashDevices) {
  await sharp({
    create: {
      width: w,
      height: h,
      channels: 4,
      background: { r: 19, g: 23, b: 34, alpha: 255 },
    },
  })
    .composite([
      {
        input: splashIcon,
        left: Math.round((w - splashIconSize) / 2),
        top: Math.round((h - splashIconSize) / 2) - Math.round(h * 0.05),
      },
    ])
    .png()
    .toFile(join(SPLASH_DIR, name));
  console.log(`  ✓ ${name}`);
}

console.log("\nAll icons and splash screens generated from icon-source.png");
