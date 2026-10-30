import { DuckDBConnection } from '@mastra/duckdb';
async function test() {
  const db = new DuckDBConnection({ path: 'C:/Users/viv1n/Documents/ZPay/observability.duckdb' });
  const conn = await db.connect();
  const spans = await (await conn.run('SELECT count(*) as count FROM spans')).getRows();
  console.log('Spans count:', spans);
}
test().catch(console.error);
