export function BrandMark({
  className = "h-6 w-6",
}: {
  className?: string;
}) {
  return (
    <img
      src="/logo-256.png"
      alt=""
      aria-hidden="true"
      draggable={false}
      decoding="async"
      className={`${className} rounded-full object-cover shadow-sm ring-1 ring-border/50`}
    />
  );
}
