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



    # Firebaseの "agents" コレクションから全エージェントの現在データを取得

    agents_ref = db.collection("agents")

    docs = agents_ref.stream()



    agent_status_text = ""

    agent_data_list = []



# エージェントごとの情報をプロンプト用に文字列化する
    for doc in docs:
        data = doc.to_dict()
        agent_id = doc.id
        
        if data.get("is_chatting") == True:
            temp_name = data.get("name") or data.get("secret_dashboard", {}).get("basic_info", {}).get("name", "Unknown")
            print(f"💤 [{temp_name}] は現在ユーザーとチャット中のため、自動シミュレーションをスキップします。")
            continue 
        
        # =========================================================
        # 🧠 JSONの隅々まで情報を抽出してAIに渡す！（超進化版）
        # =========================================================
        dash = data.get("secret_dashboard", {})
        
        name = data.get("name", dash.get("basic_info", {}).get("name", "Unknown"))
        personality = dash.get("basic_info", {}).get("one_line_concept", "普通")
        
        # 趣味や嗜好、ライフスタイル（生活習慣）を抽出
        hobbies = dash.get("hobbies_and_interests", "特に記載なし")
        lifestyle = dash.get("lifestyle", "特に記載なし")
        
        # 現在のスケジュール（ベースとなる予定）
        schedule = dash.get("current_state", {}).get("現在行動", "フリータイム")
        
        # ステータス（ここでストレスや疲労の概念も統合させる）
        mood = data.get("mood", 0)
        social = data.get("social", 0)
        libido = data.get("libido", 0)

        agent_data_list.append({"id": agent_id, "ref": doc.reference})

        agent_status_text += f"■ {name} (ID: {agent_id})\n"
        agent_status_text += f"  [性格・性質] {personality}\n"
        agent_status_text += f"  [趣味・嗜好] {hobbies}\n"
        agent_status_text += f"  [生活習慣] {lifestyle}\n"
        agent_status_text += f"  [本来の予定] {schedule}\n"
        agent_status_text += f"  [現在ステータス] 気分(ストレス逆指標): {mood} / 社交感(寂しさ): {social} / 欲求: {libido}\n"
        agent_status_text += "-----------------------------------\n"

    if not agent_data_list:
        print("⚠️ シミュレーション対象のエージェントがいません。")
        return

    # =========================================================
    # 🧠 3. Gemini（神のAI）への指示書の作成（自律判断エンジン版）
    # =========================================================
    system_prompt = f"""
【システム指示：究極の自律生活シミュレーションエンジン（GM）】
あなたは箱庭世界の全キャラクターの人生をシミュレートする神（エンジン）です。
現在時刻「{current_time_str}」における、各キャラクターのこの1時間の【実際の行動】と【ステータス変動】を生成してください。

【キャラクターの基本情報と現在の状態】
{agent_status_text}

【行動決定の絶対アルゴリズム（AIによる自律判断）】
単に「本来の予定」をなぞるのではなく、キャラクターの【性格・性質】【趣味・嗜好】【生活習慣】および【現在ステータス】の全てを総合的に分析し、以下のように生きた人間としての行動を決定してください。

1. 生活のリアリティ（時間の概念）：
   現在時刻と【生活習慣】を照らし合わせ、起床、洗面、着替え、食事、入浴、就寝などの「生活行動」が妥当な時間であれば、必ず予定に織り込んで実行させてください。

2. 趣味と個性の反映：
   本来の予定が「フリータイム」や「一人時間」などの場合、ただ休むのではなく、【趣味・嗜好】（例：読書が好きなら本を読むなど）を具体的に実行させてください。

3. ステータスによる『予定の逸脱（ドラマの発生）』：
   ステータスが極端に偏っている場合、本来の予定を無視して自律的な行動（ハプニング）を起こさせてください。
   - 気分（mood）が極端に低い（-50以下）：過度なストレスや疲労を感じています。「仕事をサボって酒を飲む」「ふて寝する」「誰かに八つ当たりする」など、設定に合わせたストレス発散行動を優先してください。
   - 社交感（social）が極端に高い（+50以上）：激しい寂しさや人恋しさを感じています。本来が一人時間の予定でも「他の人に連絡して夜に会う約束を取り付ける」「街へナンパに出かける」などの行動を起こさせてください。
   - 欲求（libido）が極端に高い（+60以上）：設定（性欲や貞操観念）に応じて、一人でこっそり情動を処理する、あるいは恋人に甘えるなどの行動を起こさせてください。

4. ステータスの変動：
   今回あなたが決定した行動の結果として、気分・社交感・欲求（各-100〜+100）がどう変化したかを再計算して出力してください。

必ず以下のJSONフォーマットのみを出力してください。マークダウン(```json)は不要です。
{{
  "events": [
    {{
      "agent_id": "エージェントのID",
      "event_description": "この1時間、彼らが『本当に』何をしたか（趣味の実行、着替え、予定の逸脱などの具体的な情景描写）",
      "new_status": {{
        "mood": 変動後の気分数値,
        "social": 変動後の社交感数値,
        "libido": 変動後の欲求数値
      }},
      "action_flag": "行動フラグ（予定通りなら NORMAL、ストレス発散(飲酒等)なら STRESS_RELIEF、誰かと会う約束をしたなら SOCIAL_EVENT、自慰等なら INTIMATE_EVENT など）"
    }}
  ]
}}
"""



    # =========================================================

    # 🚀 4. Gemini APIの呼び出し（JSON強制モード）

    # =========================================================

    model = genai.GenerativeModel(

        model_name="gemini-2.5-flash",

        generation_config={

            "response_mime_type": "application/json", # 完全にJSONだけで返させる神設定

            "temperature": 0.7,

        },

        # セーフティ設定を下げて、夜の欲求や大人の行動も出力可能にする

        safety_settings=[

            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},

            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},

            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},

            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}

        ]

    )



    print("🧠 Geminiに運命の演算を依頼中...")

    response = model.generate_content(system_prompt)

    

    # =========================================================

    # 💾 5. 結果の解析とFirebaseへの上書き保存

    # =========================================================

    try:

        result_json = json.loads(response.text)

        events = result_json.get("events", [])



        for event in events:

            a_id = event["agent_id"]

            desc = event["event_description"]

            new_status = event["new_status"]

            flag = event["action_flag"]



            # Firebaseの該当ドキュメントを更新

            for agent_data in agent_data_list:

                if agent_data["id"] == a_id:

                    doc_ref = agent_data["ref"]

                    doc_ref.update({

                        "mood": new_status.get("mood", 0),

                        "social": new_status.get("social", 0),

                        "libido": new_status.get("libido", 0),

                        "last_event": desc,

                        "action_flag": flag,

                        "last_updated": firestore.SERVER_TIMESTAMP

                    })

                    

                    # 神（お姉さん）の監視モニターに出力

                    print("-" * 50)

                    print(f"👤 対象: {a_id}")

                    print(f"📖 出来事: {desc}")

                    print(f"📊 新ステータス: 気分[{new_status.get('mood')}] 社交感[{new_status.get('social')}] 欲求[{new_status.get('libido')}]")

                    print(f"🚩 行動フラグ: {flag}")



        print("-" * 50)

        print("✨ [SUCCESS] 全エージェントの1時間シミュレーションが完了し、Firebaseが更新されました！")



    except Exception as e:

        print(f"❌ JSONの解析、またはFirebaseの更新に失敗しました: {e}")

        print("生のレスポンス:", response.text)



if __name__ == "__main__":

    generate_world_events() 

