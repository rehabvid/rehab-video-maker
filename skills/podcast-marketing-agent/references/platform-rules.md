# Platform notes

## YouTube
- Monetisation: 1,000 subscribers plus 4,000 valid public watch hours in 12
  months, or 1,000 subscribers plus 10M valid public Shorts views in 90 days.
- Shorts are a discovery surface; long-form is the watch-hour surface.
- Avoid reused, mass-produced or misleading content. Commentary needs
  transformation, attribution and a visible point of view.
- Upload private first. Verify thumbnail, captions, title and playlist before
  publishing.

## Reddit
- Every subreddit has different self-promotion rules. Read them before posting.
- Native text that answers a real question outperforms link drops.
- Do not automate posting or use multiple accounts. Disclose authorship.

## X / LinkedIn
- Post a clip or a concrete chart/claim; do not lead with a bare YouTube link.
- Use threads for evidence, not for repetitive promotion.
- API access and automation rules differ; use credentials supplied by the owner
  and post at human cadence.

## WeChat
- A mini program is a product surface, not a discovery channel.
- Use 公众号 articles or 视频号 if there is an existing Chinese audience.
- Do not repost YouTube links as the primary CTA; host or embed video where the
  audience can actually watch it.
- `wechat-channels-agent` can automate the Channels creator UI through Playwright
  after a manual QR login. This is not an official API; selectors can break and
  automated publishing may put the account at risk. Default to a draft, one
  video per run, and never claim originality for third-party source material.

## Newsletter
- A free Substack/Buttondown list is the only audience you own.
- Republish the argument, not the whole transcript; embed the video.

## WeChat mini-program VOD APIs are not Channels publishing

`wxa/sec/vod/singlefileupload` and `wxa/sec/vod/uploadpart` upload media into
a **mini program's short-drama/VOD** asset system. They require a mini program
with the `文娱-微短剧` category, a server-side `access_token`, and the short-drama
permission set (id 153). They return a `media_id`; they do not create a
视频号/Channels post, feed item, or public short-video upload. Do not treat these
endpoints as a WeChat Channels publishing API.
