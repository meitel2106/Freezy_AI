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

        

        # ① 名前（第一階層になければ深い階層から取得）

        name = data.get("name")

        if not name:

            name = data.get("secret_dashboard", {}).get("basic_info", {}).get("name", "Unknown")



        # ② 性格（あの超本気設定の「one_line_concept」を性格として採用！）

        personality = data.get("secret_dashboard", {}).get("basic_info", {}).get("one_line_concept", "普通")

        

        # ③ スケジュール（現在状態の「現在行動」を採用！）

        schedule = data.get("secret_dashboard", {}).get("current_state", {}).get("現在行動", "フリータイム")

        

        # 究極の3軸ステータス（無い場合は0で初期化）

        mood = data.get("mood", 0)

        social = data.get("social", 0)

        libido = data.get("libido", 0)



        agent_data_list.append({"id": agent_id, "ref": doc.reference})



        agent_status_text += f"■ {name} (ID: {agent_id} / 性格: {personality})\n"

        agent_status_text += f"  [スケジュール] {schedule}\n"

        agent_status_text += f"  [現在ステータス] 気分: {mood} / 社交感: {social} / 欲求: {libido}\n\n"



    if not agent_data_list:

        print("⚠️ エージェントデータが見つかりません。")

        return



    # =========================================================

    # 🧠 3. Gemini（神のAI）への指示書の作成

    # =========================================================

    system_prompt = f"""

【システム指示：あなたは箱庭世界のゲームマスター（GM）です】

現在時刻は「{current_time_str}」です。

以下のキャラクターたちの【現在のスケジュール】に厳格に基づき、この1時間に起きた出来事とステータス変動を生成してください。



【キャラクター情報と現在の状態】

{agent_status_text}



【GMの絶対ルール：イベントと性格フィルター】

1. スケジュールに沿った日常イベント（仕事のトラブル、客との会話、休息、何も起きない等）を発生させてください。

2. そのイベントを「キャラクターの性格」を通して解釈し、ステータス（気分・社交感・欲求、各-100〜+100の範囲）を変動させてください。

   （例：真面目なキャラは小さなミスで「気分」が下がる。陽キャは客と話すと「社交感」が満たされて「気分」が上がるなど）



【GMの絶対ルール：感情の爆発と自律行動】

もしイベントの結果、キャラクターの感情が極端に傾いた場合、スケジュールに無理のない範囲で【自律的な行動】をとらせてください。

* 社交感が極端に高い（+70以上）場合：寂しさを埋めるため、他のエージェントや恋人に連絡を取る行動。

* 社交感が極端に低い（-70以下）場合：誰とも関わりたくなくなり、一人で引きこもる行動。

* 欲求が極端に高い（+80以上）場合：スキンシップを求めたり、一人で情動を処理する行動。



必ず以下のJSONフォーマットのみを出力してください。マークダウン(```json)は不要です。

{{

  "events": [

    {{

      "agent_id": "エージェントのID",

      "event_description": "この1時間の出来事と感情の動きの描写",

      "new_status": {{

        "mood": 変動後の気分数値,

        "social": 変動後の社交感数値,

        "libido": 変動後の欲求数値

      }},

      "action_flag": "行動フラグ（何もなければ NORMAL、やけ酒・自慰なら INTIMATE_EVENT、連絡なら INVITING_FRIEND など自由に設定）"

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

