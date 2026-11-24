import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"])
        pg=await b.new_page(viewport={"width":1340,"height":760})
        await pg.goto("file:///home/claude/work/hazbrief_pitch.html"); await pg.wait_for_timeout(800)
        await pg.pdf(path="hazbrief_pitch.pdf",width="13.333in",height="7.5in",print_background=True,prefer_css_page_size=True)
        ov=await pg.evaluate("[...document.querySelectorAll('.s')].map((s,i)=>[i+1,s.scrollHeight,s.scrollWidth])")
        print(ov)
        els=await pg.query_selector_all(".s")
        for i,e in enumerate(els): await e.screenshot(path=f"s{i+1:02d}.png")
        await b.close()
asyncio.run(main())
