export function BrandMark({
  className = "h-6 w-6",
  priority = false,
}: {
  className?: string;
  priority?: boolean;
}) {
  return (
    <img
      src="/logo.png"
      alt="Vibe-Trading"
      aria-hidden="true"
      draggable={false}
      decoding={priority ? "sync" : "async"}
      className={`${className} object-contain select-none`}
    />
  );
}
