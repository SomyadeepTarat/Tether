import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** Render untrusted model Markdown as React elements; raw HTML stays disabled. */
export function ReportContent({content}:{content:string}) {
  return <div className="report-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={['img','a']} unwrapDisallowed>{content}</Markdown></div>;
}

export function sectionTitle(id:string) {
  const titles:Record<string,string>={cost_comparison:'Cloud costs',deployment_comparison:'Deployment approaches',comparison_comparison:'Comparison table',recommendation_comparison:'Final recommendation',serverless_comparison:'Serverless comparison'};
  return titles[id]||id.replaceAll('_',' ');
}
