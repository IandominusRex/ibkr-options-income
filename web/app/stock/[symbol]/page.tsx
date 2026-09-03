export default async function StockPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  return (
    <div className="px-8 py-6">
      <h1 className="font-mono text-2xl text-content">{symbol.toUpperCase()}</h1>
      <p className="mt-2 text-sm text-muted">Analysis arrives in Milestone 3.</p>
    </div>
  );
}