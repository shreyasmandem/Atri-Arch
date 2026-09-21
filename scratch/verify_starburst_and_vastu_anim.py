import asyncio
import base64
import json
import subprocess
import tempfile
import urllib.request
import websockets

async def verify():
    edge_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    tmpdir = tempfile.mkdtemp()
    cmd = [
        edge_path, '--headless', '--disable-gpu', '--remote-debugging-port=9245',
        '--window-size=1440,1100', '--remote-allow-origins=*', f'--user-data-dir={tmpdir}',
        'about:blank'
    ]
    proc = subprocess.Popen(cmd)
    try:
        ws_url = None
        for _ in range(30):
            await asyncio.sleep(0.2)
            try:
                data = urllib.request.urlopen('http://127.0.0.1:9245/json/version').read()
                ws_url = json.loads(data.decode()).get('webSocketDebuggerUrl')
                if ws_url: break
            except Exception: pass

        if not ws_url:
            print("Failed to get CDP ws_url")
            return

        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({'id': 1, 'method': 'Target.getTargets'}))
            targets = json.loads(await ws.recv())
            page_target = next(t for t in targets['result']['targetInfos'] if t['type'] == 'page')
            page_ws_url = f"ws://127.0.0.1:9245/devtools/page/{page_target['targetId']}"
            
            async with websockets.connect(page_ws_url) as page_ws:
                await page_ws.send(json.dumps({'id': 2, 'method': 'Runtime.enable'}))
                await page_ws.send(json.dumps({'id': 3, 'method': 'Page.enable'}))
                
                # Navigate to the app now that DevTools is connected
                await page_ws.send(json.dumps({'id': 4, 'method': 'Page.navigate', 'params': {'url': 'http://127.0.0.1:8001/'}}))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 4:
                        break

                # ─── 1. CAPTURE AT t = 0.5s: Pure Void, Gold Alone, Zero Stars ───
                await asyncio.sleep(0.5)
                eval_void = """
                (() => {
                    const canvas = document.getElementById('space-stars');
                    const gold = document.querySelector('.intro-logo-gold');
                    const silver = document.querySelector('.intro-logo-silver');
                    const isLoading = document.body.classList.contains('is-loading');
                    return {
                        isLoading,
                        goldOpacity: gold ? window.getComputedStyle(gold).opacity : null,
                        silverOpacity: silver ? window.getComputedStyle(silver).opacity : null,
                        canvasBg: canvas ? window.getComputedStyle(canvas).backgroundColor : null
                    };
                })()
                """
                await page_ws.send(json.dumps({
                    'id': 101, 'method': 'Runtime.evaluate', 'params': {'expression': eval_void, 'returnByValue': True}
                }))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 101:
                        print("t = 0.5s Void Check:", m.get('result', {}).get('result', {}).get('value'))
                        break

                await page_ws.send(json.dumps({'id': 102, 'method': 'Page.captureScreenshot'}))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 102:
                        with open(r'C:\Users\chari\.gemini\antigravity\brain\5ea0d27d-2c00-4110-be2c-6345e1da8461\verify_intro_star_void.png', 'wb') as f:
                            f.write(base64.b64decode(m['result']['data']))
                        print("Saved verify_intro_star_void.png")
                        break

                # ─── 2. CAPTURE AT t = 1.45s: Exact Merge Moment -> Starburst Eruption! ───
                await asyncio.sleep(0.95) # Total elapsed ~1.45s
                eval_burst = """
                (() => {
                    const curtain = document.getElementById('intro-curtain');
                    const gold = document.querySelector('.intro-logo-gold');
                    const silver = document.querySelector('.intro-logo-silver');
                    return {
                        curtainVisible: curtain ? window.getComputedStyle(curtain).display : null,
                        goldOpacity: gold ? window.getComputedStyle(gold).opacity : null,
                        silverOpacity: silver ? window.getComputedStyle(silver).opacity : null
                    };
                })()
                """
                await page_ws.send(json.dumps({
                    'id': 103, 'method': 'Runtime.evaluate', 'params': {'expression': eval_burst, 'returnByValue': True}
                }))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 103:
                        print("t = 1.45s Merge & Starburst Check:", m.get('result', {}).get('result', {}).get('value'))
                        break

                await page_ws.send(json.dumps({'id': 104, 'method': 'Page.captureScreenshot'}))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 104:
                        with open(r'C:\Users\chari\.gemini\antigravity\brain\5ea0d27d-2c00-4110-be2c-6345e1da8461\verify_intro_starburst_merge.png', 'wb') as f:
                            f.write(base64.b64decode(m['result']['data']))
                        print("Saved verify_intro_starburst_merge.png")
                        break

                # ─── 3. CAPTURE AT t = 3.6s: Studio Revealed, Ambient Stars Drifting ───
                await asyncio.sleep(2.15) # Total elapsed ~3.6s
                eval_studio = """
                (() => {
                    const curtain = document.getElementById('intro-curtain');
                    const isLoading = document.body.classList.contains('is-loading');
                    const compose = document.getElementById('compose');
                    return {
                        isLoading,
                        curtainDisplay: curtain ? curtain.style.display : null,
                        composeOpacity: compose ? window.getComputedStyle(compose).opacity : null
                    };
                })()
                """
                await page_ws.send(json.dumps({
                    'id': 105, 'method': 'Runtime.evaluate', 'params': {'expression': eval_studio, 'returnByValue': True}
                }))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 105:
                        print("t = 3.6s Studio Reveal Check:", m.get('result', {}).get('result', {}).get('value'))
                        break

                await page_ws.send(json.dumps({'id': 106, 'method': 'Page.captureScreenshot'}))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 106:
                        with open(r'C:\Users\chari\.gemini\antigravity\brain\5ea0d27d-2c00-4110-be2c-6345e1da8461\verify_studio_revealed.png', 'wb') as f:
                            f.write(base64.b64decode(m['result']['data']))
                        print("Saved verify_studio_revealed.png")
                        break

                # ─── 4. TEST VASTU DYNAMIC ANIMATION ───
                # Scroll into Vastu card view
                scroll_vastu = """
                (() => {
                    const card = document.getElementById('vastu-card');
                    card?.scrollIntoView({ behavior: 'instant', block: 'center' });
                    const stations = Array.from(document.querySelectorAll('#stance-scale .stance-station')).map(s => s.innerText.trim());
                    const pillText = document.getElementById('stance-status-pill')?.innerText.trim();
                    const hasPctElements = !!document.querySelector('.station-pct') || !!document.getElementById('stance-weight');
                    return { stations, pillText, hasPctElements };
                })()
                """
                await page_ws.send(json.dumps({
                    'id': 107, 'method': 'Runtime.evaluate', 'params': {'expression': scroll_vastu, 'returnByValue': True}
                }))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 107:
                        print("Vastu Baseline (Zero Percentages):", m.get('result', {}).get('result', {}).get('value'))
                        break

                await asyncio.sleep(0.4)

                # Capture baseline resting state (Balanced)
                await page_ws.send(json.dumps({'id': 1071, 'method': 'Page.captureScreenshot'}))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 1071:
                        with open(r'C:\Users\chari\.gemini\antigravity\brain\5ea0d27d-2c00-4110-be2c-6345e1da8461\verify_vastu_baseline_balanced.png', 'wb') as f:
                            f.write(base64.b64decode(m['result']['data']))
                        print("Saved verify_vastu_baseline_balanced.png")
                        break

                # Click Forward to Station 3 (Strict)
                click_strict = """
                (() => {
                    const st3 = document.querySelector('#stance-scale [data-val="3"]');
                    st3?.click();
                    const fill = document.getElementById('stance-track-fill');
                    const ticks = Array.from(document.querySelectorAll('.stance-tick')).map(t => ({
                        covered: t.classList.contains('is-covered'),
                        igniting: t.classList.contains('is-igniting')
                    }));
                    return {
                        val: document.getElementById('stance')?.value,
                        name: document.getElementById('stance-name')?.textContent,
                        isAdvancing: fill?.classList.contains('is-advancing'),
                        st3Active: st3?.classList.contains('is-active'),
                        st3Impacted: st3?.classList.contains('is-impacted'),
                        ticks
                    };
                })()
                """
                await page_ws.send(json.dumps({
                    'id': 108, 'method': 'Runtime.evaluate', 'params': {'expression': click_strict, 'returnByValue': True}
                }))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 108:
                        print("Vastu Forward to Strict Check:", m.get('result', {}).get('result', {}).get('value'))
                        break

                await page_ws.send(json.dumps({'id': 109, 'method': 'Page.captureScreenshot'}))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 109:
                        with open(r'C:\Users\chari\.gemini\antigravity\brain\5ea0d27d-2c00-4110-be2c-6345e1da8461\verify_vastu_forward_strict.png', 'wb') as f:
                            f.write(base64.b64decode(m['result']['data']))
                        print("Saved verify_vastu_forward_strict.png")
                        break

                await asyncio.sleep(0.5)

                # Click Forward to Station 4 (Orthodox)
                click_orthodox = """
                (() => {
                    const st4 = document.querySelector('#stance-scale [data-val="4"]');
                    st4?.click();
                    const fill = document.getElementById('stance-track-fill');
                    const ticks = Array.from(document.querySelectorAll('.stance-tick')).map(t => ({
                        covered: t.classList.contains('is-covered'),
                        igniting: t.classList.contains('is-igniting')
                    }));
                    return {
                        val: document.getElementById('stance')?.value,
                        name: document.getElementById('stance-name')?.textContent,
                        isAdvancing: fill?.classList.contains('is-advancing'),
                        st4Active: st4?.classList.contains('is-active'),
                        st4Impacted: st4?.classList.contains('is-impacted'),
                        ticks
                    };
                })()
                """
                await page_ws.send(json.dumps({
                    'id': 110, 'method': 'Runtime.evaluate', 'params': {'expression': click_orthodox, 'returnByValue': True}
                }))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 110:
                        print("Vastu Forward to Orthodox Check:", m.get('result', {}).get('result', {}).get('value'))
                        break

                await page_ws.send(json.dumps({'id': 111, 'method': 'Page.captureScreenshot'}))
                while True:
                    m = json.loads(await page_ws.recv())
                    if m.get('id') == 111:
                        with open(r'C:\Users\chari\.gemini\antigravity\brain\5ea0d27d-2c00-4110-be2c-6345e1da8461\verify_vastu_forward_orthodox.png', 'wb') as f:
                            f.write(base64.b64decode(m['result']['data']))
                        print("Saved verify_vastu_forward_orthodox.png")
                        break

    finally:
        try:
            proc.kill()
        except Exception:
            pass

if __name__ == '__main__':
    asyncio.run(verify())
