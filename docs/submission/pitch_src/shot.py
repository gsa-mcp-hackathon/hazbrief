import asyncio, sys
from playwright.async_api import async_playwright
B="file:///mnt/user-data/uploads/hazbrief-mcp/docs/briefs/csx-point-of-rocks-night/brief.html"
S="file:///mnt/user-data/uploads/hazbrief-mcp/docs/incidents/problem_us_damage.svg"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"])
        pg=await b.new_page(viewport={"width":1440,"height":1000},device_scale_factor=2)
        await pg.goto(B,wait_until="load"); await pg.wait_for_timeout(1500)
        el=pg.locator("#section-ics201")
        print(await el.evaluate("e=>[e.tagName,e.offsetWidth,e.offsetHeight,getComputedStyle(e).display,e.parentElement.id,e.parentElement.className]"))
        await el.evaluate("e=>{let n=e;while(n){ if(n.tagName==='DETAILS') n.open=true; if(n.style) {if(getComputedStyle(n).display==='none') n.style.display='block'}; n=n.parentElement}; e.querySelectorAll('details').forEach(d=>d.open=true)}")
        await pg.wait_for_timeout(500)
        print(await el.evaluate("e=>[e.offsetWidth,e.offsetHeight]"))
        await el.screenshot(path="ics201.png")
        await pg.goto(S); await pg.set_viewport_size({"width":960,"height":794}); await pg.screenshot(path="usmap.png")
        await b.close()
asyncio.run(main())
