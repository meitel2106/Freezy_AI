import os

import json

import datetime

import firebase_admin

from firebase_admin import credentials, firestore

import google.generativeai as genai



# =========================================================

# 👑 1. 初期設定（APIキーとFirebaseの認証）

# =========================================================

# 🚨 実際のキーは絶対にここに書かず、環境変数からのみ取得する！

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:

    raise ValueError("GEMINI_API_KEYが設定されていません。")



genai.configure(api_key=GEMINI_API_KEY)



# Firebaseの初期化（※ローカルテスト時はファイルから、GitHubでは環境変数から読み込む設計に拡張）

firebase_cred_path = "firebase_credentials.json"

if not os.path.exists(firebase_cred_path):

    # GitHub Actions等の環境変数から読み込む場合の処理

    firebase_cred_dict = json.loads(os.environ.get("FIREBASE_CREDENTIALS_JSON"))

    cred = credentials.Certificate(firebase_cred_dict)

else:

    # ローカルでテストする場合の処理

    cred = credentials.Certificate(firebase_cred_path)



firebase_admin.initialize_app(cred)

db = firestore.client()



# =========================================================

# 📂 agents.json の自動同期機能（進化版）

# =========================================================

def auto_sync_agents():

    json_path = "agents.json"

    if os.path.exists(json_path):

        print("🔄 agents.json からエージェントデータを自動同期しています...")

        with open(json_path, "r", encoding="utf-8") as f:

            agents_data = json.load(f)

            

        # 超本気JSONが {"agents": [ ... ]} という形になっている場合に対応！

        if isinstance(agents_data, dict) and "agents" in agents_data:

            agent_list = agents_data["agents"]

        elif isinstance(agents_data, list):

            agent_list = agents_data

        else:

            print("⚠️ agents.json の形式が想定と異なります。")

            return



        for data in agent_list:

            agent_id = data.get("id")

            if not agent_id:

                continue

            doc_ref = db.collection("agents").document(agent_id)

            doc_ref.set(data, merge=True)

        print("✨ agents.json の自動同期が完了しました！\n")

    else:

        print("⚠️ agents.json が見つかりませんでした。既存のFirebaseデータで続行します。\n")



# スクリプト実行時に自動同期を走らせる

auto_sync_agents()





# =========================================================

# 🕰️ 2. 現在時間の取得とマスタープロンプトの準備

# =========================================================

# ⏰ サーバーの場所に関わらず、強制的に日本時間（JST: UTC+9）を取得する！

JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')

now = datetime.datetime.now(JST)

current_time_str = now.strftime("%Y-%m-%d %H:00")



def generate_world_events():
    print(f"🌍 [WORLD_SIMULATOR] {current_time_str} のシミュレーションを開始します...")

    agents_ref = db.collection("agents")
    docs = agents_ref.stream()

    agent_status_text = ""
    agent_data_list = []

    for doc in docs:
        data = doc.to_dict()
        agent_id = doc.id
        
        if data.get("is_chatting") == True:
            temp_name = data.get("name") or data.get("secret_dashboard", {}).get("basic_info", {}).get("name", "Unknown")
            print(f"💤 [{temp_name}] はチャット中のため、スキップします。")
            continue 
        
        dash = data.get("secret_dashboard", {})
        name = data.get("name", dash.get("basic_info", {}).get("name", "Unknown"))
        personality = dash.get("basic_info", {}).get("one_line_concept", "普通")
        schedule = dash.get("current_state", {}).get("現在行動", "フリータイム")
        
        mood = data.get("mood", 0)
        social = data.get("social", 0)
        libido = data.get("libido", 0)

        # =========================================================
        # 🌟 1. 現在進行中の継続イベントがあるかチェック！
        # =========================================================
        ongoing_event = data.get("ongoing_event", {})
        ongoing_name = ongoing_event.get("name", "")
        ongoing_turns = ongoing_event.get("remaining_turns", 0)

        if ongoing_turns > 0:
            ongoing_instruction = f"🚨【継続イベント実行中】現在「{ongoing_name}」の真っ最中（残り{ongoing_turns}ターン）です。通常の予定を無視し、このイベントの続きを30分間どう過ごしたか描写してください。"
        else:
            ongoing_instruction = "【継続イベント】現在なし。通常のスケジュールや自律判断で行動してください。"

        # 更新時に古いデータを参照できるように raw_data もリストに入れておく
        agent_data_list.append({"id": agent_id, "ref": doc.reference, "raw_data": data})

        agent_status_text += f"■ {name} (ID: {agent_id})\n"
        agent_status_text += f"  [本来の予定] {schedule}\n"
        agent_status_text += f"  {ongoing_instruction}\n"
        agent_status_text += f"  [現在ステータス] 気分: {mood} / 社交感: {social} / 欲求: {libido}\n"
        agent_status_text += "-----------------------------------\n"

    if not agent_data_list:
        print("⚠️ シミュレーション対象のエージェントがいません。")
        return

    # =========================================================
    # 🧠 2. Geminiへのマスタープロンプト（自律ターン予約機能付き）
    # =========================================================
    system_prompt = f"""
【システム指示：究極の自律生活シミュレーションエンジン（GM）】
現在時刻「{current_time_str}」における、各キャラクターのこの30分間の【実際の行動】と【ステータス変動】を生成してください。

【キャラクターの状態と指示】
{agent_status_text}

【継続イベント（Ongoing Event）の自律予約ルール】
もし今回の行動で、日常のスケジュールから逸脱した「数時間にわたるイベント（例：長時間のショッピング、突発的な日帰り旅行、濃密な夜の営み、親友との長電話など）」が新しく始まった場合、あなたの疲労度や性格、明日の予定を考慮して、**そのイベントが何時間（何ターン）続くかを自律的に決定して予約**してください。（※1ターン＝30分）
※すでに継続イベント中の場合や、30分以内で終わる単発行動の場合は「ongoing_event_trigger」を null にしてください。

必ず以下のJSONフォーマットのみを出力してください。
{{
  "events": [
    {{
      "agent_id": "エージェントのID",
      "event_description": "この30分間の具体的な情景描写（継続中の場合はその経過）",
      "new_status": {{
        "mood": 変動後の数値,
        "social": 変動後の数値,
        "libido": 変動後の数値
      }},
      "action_flag": "NORMAL や INTIMATE_EVENT など",
      "ongoing_event_trigger": {{
        "type": "SHOPPING_OR_TRIP_ETC",
        "name": "イベントの具体的な名前（例：秋服の買い出し、ユーザーとの甘い夜）",
        "turns": 予約するターン数(整数。例：2時間なら4)
      }} // ※予約しない場合はキーごと省略するか null にすること
    }}
  ]
}}
"""

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json", "temperature": 0.7},
        safety_settings=[
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    )

    print("🧠 Geminiに運命とターンの演算を依頼中...")
    response = model.generate_content(system_prompt)
    
    # =========================================================
    # 💾 3. 解析と「予約ターン」の減算・保存処理
    # =========================================================
    try:
        result_json = json.loads(response.text)
        events = result_json.get("events", [])

        for event in events:
            a_id = event["agent_id"]
            desc = event["event_description"]
            new_status = event["new_status"]
            flag = event.get("action_flag", "NORMAL")
            trigger = event.get("ongoing_event_trigger")

            for agent_data in agent_data_list:
                if agent_data["id"] == a_id:
                    doc_ref = agent_data["ref"]
                    raw_data = agent_data["raw_data"]
                    
                    update_data = {
                        "mood": new_status.get("mood", 0),
                        "social": new_status.get("social", 0),
                        "libido": new_status.get("libido", 0),
                        "last_event": desc,
                        "action_flag": flag,
                        "last_updated": firestore.SERVER_TIMESTAMP
                    }

                    # 🌟 継続イベントのターン管理ロジック 🌟
                    current_ongoing = raw_data.get("ongoing_event", {})
                    
                    if trigger and trigger.get("turns", 0) > 0:
                        # ① AIが【新規イベント】を予約した！
                        print(f"🎉 [NEW_EVENT] {a_id} が「{trigger.get('name')}」を {trigger.get('turns')} ターン予約しました！")
                        # 今回すでに1ターン（30分）経過したので、保存する残りターンは -1 しておく
                        update_data["ongoing_event"] = {
                            "type": trigger.get("type", "CUSTOM"),
                            "name": trigger.get("name", "特殊イベント"),
                            "remaining_turns": max(0, trigger.get("turns") - 1)
                        }
                    elif current_ongoing and current_ongoing.get("remaining_turns", 0) > 0:
                        # ② 既存のイベントを【継続中】（ターンを1減らす）
                        remaining = current_ongoing["remaining_turns"] - 1
                        if remaining > 0:
                            current_ongoing["remaining_turns"] = remaining
                            update_data["ongoing_event"] = current_ongoing
                            print(f"⏳ [ONGOING] {a_id} の「{current_ongoing.get('name')}」継続中（残り {remaining} ターン）")
                        else:
                            # ターンが0になったらイベント終了！（フィールドごと削除）
                            update_data["ongoing_event"] = firestore.DELETE_FIELD
                            print(f"🏁 [FINISHED] {a_id} の「{current_ongoing.get('name')}」が終了し、日常に戻りました！")
                    else:
                        # ③ 何もない日常
                        update_data["ongoing_event"] = firestore.DELETE_FIELD

                    doc_ref.update(update_data)
                    
                    print("-" * 50)
                    print(f"📖 {desc}")

        print("✨ [SUCCESS] シミュレーション完了！ターン管理がFirestoreに保存されました！")

    except Exception as e:
        print(f"❌ 解析失敗: {e}")
        print("生のレスポンス:", response.text)

if __name__ == "__main__":
    generate_world_events()

