import { PageState } from "../../components/common/PageState";
import type { NewsItem } from "../../domain/news";

export interface NewsTimelineProps {
  news: NewsItem[];
}

export function NewsTimeline({ news }: NewsTimelineProps) {
  return (
    <section
      className="research-panel"
      aria-labelledby="market-news-title"
    >
      <div className="section-heading">
        <div>
          <p className="section-kicker">SOURCE TIMELINE</p>
          <h2 id="market-news-title">市场资讯</h2>
        </div>
      </div>
      {news.length === 0 ? (
        <PageState state="empty" message="当前标的暂无可追溯资讯。" />
      ) : (
        <ol className="news-timeline">
          {news.map((item) => (
            <li key={item.id}>
              <article className="news-timeline__entry">
                <div className="news-timeline__marker" aria-hidden="true" />
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.summary}</p>
                  <a
                    className="text-link"
                    href={item.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {item.source}
                  </a>
                  <dl className="metadata-list">
                    <div>
                      <dt>发布时间</dt>
                      <dd>
                        <time dateTime={item.publishedAt}>
                          {item.publishedAt}
                        </time>
                      </dd>
                    </div>
                    <div>
                      <dt>获取时间</dt>
                      <dd>
                        <time dateTime={item.fetchedAt}>
                          {item.fetchedAt}
                        </time>
                      </dd>
                    </div>
                  </dl>
                </div>
              </article>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
