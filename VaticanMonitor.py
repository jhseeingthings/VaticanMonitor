from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
import smtplib
from email.mime.text import MIMEText

# ====================== 配置区 ======================
SMTP_SERVER = "smtp.163.com"
SMTP_PORT = 25
SENDER_EMAIL = ""
SENDER_AUTH_CODE = ""
RECEIVER_EMAIL = [""]
TARGET_URL = "https://tickets.museivaticani.va/home/visit/2/1777651200000/1/"
CHECK_INTERVAL = 30

GUIDE_TICKET_ALERT_INTERVAL = 3600
last_guide_alert_time = 0
last_guide_alert_flag = False

click_once = False
# ====================================================

def get_vatican_ticket_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            slow_mo=300,
            args=["--no-sandbox", "--disable-gpu"]
        )
        page = browser.new_page()
        page.goto(TARGET_URL, timeout=60000)
        page.wait_for_load_state("networkidle")

        getTickectsAvail(page)
        browser.close()
def getTickectsAvail(page):
    global last_guide_alert_time, last_guide_alert_flag, click_once
    now = time.time()
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    tickets = soup.find_all('div', class_='muvaTicketMainDiv')

    # 用 enumerate 记录票块索引，精准定位
    for i, ticket in enumerate(tickets):
        title_elem = ticket.find('span', class_='muvaTicketTitle') or ticket.find('span', class_='muvaTicketTitleLong')
        title = title_elem.get_text(strip=True) if title_elem else "无标题"
        button = ticket.find('button')
        btn_text = button.get_text(strip=True) if button else "无按钮"

        # ===================== 普通票逻辑（保持稳定，精准点击） =====================
        if title == "Musei Vaticani - Biglietti d'ingresso" and btn_text == "PRENOTA":
            if not click_once:
                print("✅ 发现普通票PRENOTA按钮，开始检查真实余票...")
                try:
                    # 精准点击当前票块的按钮
                    target_ticket = page.locator(".muvaTicketMainDiv").nth(i)
                    btn_locator = target_ticket.locator("button")
                    
                    btn_locator.wait_for(state="visible", timeout=15000)
                    btn_locator.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)

                    # 解析可用时间段
                    time_html = page.content()
                    with open("after_click_normal.html", "w", encoding="utf-8") as f:
                        f.write(BeautifulSoup(time_html, "html.parser").prettify())

                    time_soup = BeautifulSoup(time_html, "html.parser")
                    time_slots = time_soup.find_all("div", class_="muvaCalendarDayBorder")
                    available_times = []

                    for slot in time_slots:
                        class_list = slot.get("class", [])
                        if "disabled" not in class_list:
                            time_text = slot.find("div", class_="muvaCalendarNumber").get_text(strip=True)
                            if time_text <= "17:00" and time_text not in available_times:
                                available_times.append(time_text)

                    # 有票才发邮件
                    if len(available_times) > 0:
                        print(f"🎉 普通票真实有票！可用时段：{available_times}")
                        send_email_alert(title, "普通票", available_times)
                    else:
                        print("❌ 假阳性：所有时段均已满")

                    click_once = True

                except Exception as e:
                    print(f"❌ 普通票检查失败：{e}")

        # ===================== 导览票逻辑（新增语言选择步骤，100%精准） =====================
        elif title == "Musei Vaticani - Visite Guidate Singoli Musei":
            if btn_text == "PRENOTA":
                try:
                    print(f"✅ 发现导览票PRENOTA按钮（第{i+1}个票块），开始检查...")
                    
                    # 1. 精准点击当前导览票块的按钮
                    target_ticket = page.locator(".muvaTicketMainDiv").nth(i)
                    btn_locator = target_ticket.locator("button")
                    btn_locator.wait_for(state="visible", timeout=15000)
                    btn_locator.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)

                    # ==============================================
                    # ✅ 新增：导览票语言选择步骤（选Inglese）
                    # ==============================================
                    print("🔍 检查是否需要选择导览语言...")
                    # 用最稳定的data-cy属性定位语言下拉框（不会随前端编译变化）
                    lang_dropdown = page.locator('[data-cy="visitLang"]')
                    
                    # 如果页面出现了语言选择框，执行选择
                    if lang_dropdown.count() > 0:
                        print("📝 找到语言选择框，开始选择Inglese...")
                        try:
                            # 1. 点击下拉箭头，展开选项列表
                            dropdown_arrow = lang_dropdown.locator('..').locator('.icon-down-open')
                            dropdown_arrow.wait_for(state="visible", timeout=10000)
                            dropdown_arrow.click()
                            page.wait_for_timeout(1000)

                            # 2. 定位并点击Inglese选项
                            english_option = page.locator('.select__list--item:has-text("Inglese")')
                            english_option.wait_for(state="visible", timeout=10000)
                            english_option.click()
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(1500)

                            print("✅ 语言选择完成：Inglese")
                        except Exception as lang_e:
                            print(f"⚠️ 语言选择失败，跳过：{lang_e}")
                    else:
                        print("ℹ️ 无需选择语言，直接检查时段")

                    # 3. 解析导览票时段
                    time_html = page.content()
                    with open("after_click_guide.html", "w", encoding="utf-8") as f:
                        f.write(BeautifulSoup(time_html, "html.parser").prettify())

                    time_soup = BeautifulSoup(time_html, "html.parser")
                    time_slots = time_soup.find_all("div", class_="muvaCalendarDayBorder")
                    has_real_ticket = False
                    available_times = []

                    for slot in time_slots:
                        if "disabled" not in slot.get("class", []):
                            has_real_ticket = True
                            time_text = slot.find("div", class_="muvaCalendarNumber").get_text(strip=True)
                            if time_text <= "17:00" and time_text not in available_times:
                                available_times.append(time_text)

                    # 有票且在冷却期外才发邮件
                    if has_real_ticket:
                        if now - last_guide_alert_time >= GUIDE_TICKET_ALERT_INTERVAL or not last_guide_alert_flag:
                            print(f"🎉 导览票真实有票！时段：{available_times}")
                            send_email_alert(title, "导览票", available_times)
                            last_guide_alert_time = now
                            last_guide_alert_flag = True
                    else:
                        print("❌ 导览票全满")
                        
                except Exception as e:
                    print(f"❌ 导览票检查失败：{e}")
            else:
                last_guide_alert_flag = False

def send_email_alert(title, ticket_type, available_times=None):
    if "普通票" in ticket_type:
        subject = "❗️梵蒂冈普通票可预订！"
    else:
        subject = "ℹ️ 梵蒂冈导览票可预订"

    # 拼接可用时间
    time_str = ""
    if available_times and len(available_times) > 0:
        time_str = "可预订时段：" + " | ".join(available_times) + "\n"

    content = f"""
门票类别：{title}
{time_str}
当前状态：可预订
门票链接：{TARGET_URL}
"""
    msg = MIMEText(content, 'plain', 'utf-8')
    msg['From'] = SENDER_EMAIL
    msg['To'] = ','.join(RECEIVER_EMAIL)
    msg['Subject'] = subject

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_AUTH_CODE)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print("✅ 邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")

if __name__ == '__main__':
    print("🚀 梵蒂冈门票监控已启动...")
    while True:
        click_once = False
        try:
            get_vatican_ticket_page()
        except Exception as e:
            print(f"⚠️ 监控出错：{e}")

        print(f"⏳ {CHECK_INTERVAL}秒后再次检查...\n")
        time.sleep(CHECK_INTERVAL)
