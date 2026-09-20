import os
import json
import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# =========================================================
# 👑 1. 初期設定（APIキーとFirebaseの認証）
# =========================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEYが設定されていません。")

genai.configure(api_key=GEMINI_API_KEY)

firebase_cred_path = "firebase_credentials.json"
if not os.path.exists(firebase_cred_path):
    firebase_cred_dict = json.loads(os.environ.get("FIREBASE_CREDENTIALS_JSON"))
    cred = credentials.Certificate(firebase_cred_dict)
else:
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

auto_sync_agents()


# =========================================================
# 🕰️ 2. 現在時間の取得とマスタープロンプトの準備
# =========================================================
JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')
now = datetime.datetime.now(JST)
current_time_str = now.strftime("%Y-%m-%d %H:00")

def generate_world_events():
    print(f"🌍 [WORLD_SIMULATOR] {current_time_str} のシミュレーションを開始します...")

    agents_ref = db.collection("agents")
    docs = agents_ref.stream()

    agent_status_text = ""
    agent_data_list = []
    
    # 🌟 街にいる全エージェントの「名前とIDのリスト」をAIに教えるための辞書
    all_agents_info = []

    for doc in docs:
        data = doc.to_dict()
        agent_id = doc.id
        
        name = data.get("name")
        if not name:
            name = data.get("secret_dashboard", {}).get("basic_info", {}).get("name", "Unknown")

        all_agents_info.append(f"- {name} (ID: {agent_id})")

        # 📦 ユーザーイベントの透明化処理
        ongoing = data.get("ongoing_event")
        if ongoing and ongoing.get("type") == "USER_INTERACTION":
            ongoing = None 

        if ongoing:
            remaining = ongoing.get("remaining_turns", 0)
            print(f"⏳ [ONGOING] {agent_id} の「{ongoing.get('name')}」継続中（残り {remaining} ターン）")

        personality = data.get("secret_dashboard", {}).get("basic_info", {}).get("one_line_concept", "普通")
        schedule = data.get("secret_dashboard", {}).get("current_state", {}).get("現在行動", "フリータイム")
        
        mood = data.get("mood", 0)
        social = data.get("social", 0)
        libido = data.get("libido", 0)

        # 🌟 現在の人間関係（相関図）を取得
        relationships = data.get("relationships", {})
        rel_text = "特になし"
        if relationships:
            rel_list = []
            for target_id, rel_data in relationships.items():
                rel_list.append(f"  ・{target_id} (関係: {rel_data.get('type')}) - {rel_data.get('notes')}")
            rel_text = "\n".join(rel_list)

        agent_data_list.append({
            "id": agent_id, 
            "ref": doc.reference,
            "raw_data": data,
            "is_user_event": (data.get("ongoing_event", {}).get("type") == "USER_INTERACTION")
        })

        agent_status_text += f"■ {name} (ID: {agent_id} / 性格: {personality})\n"
        agent_status_text += f"  [スケジュール] {schedule}\n"
        agent_status_text += f"  [交友関係] \n{rel_text}\n"
        agent_status_text += f"  [現在ステータス] 気分: {mood} / 社交感: {social} / 欲求: {libido}\n\n"

    if not agent_data_list:
        print("⏸️ 現在、裏側で自律行動させるフリーなエージェントがいません。Gemini APIの呼び出しをスキップします。")
        return  

    all_agents_str = "\n".join(all_agents_info)

    # =========================================================
    # 🧠 3. Geminiへのマスタープロンプト（人間関係構築機能付き！）
    # =========================================================
    system_prompt = f"""
【システム指示：究極の自律生活＆人間関係シミュレーションエンジン（GM）】
現在時刻「{current_time_str}」における、各キャラクターのこの30分間の【実際の行動】と【ステータス変動】を生成してください。

【この街に存在する全エージェントのリスト】
{all_agents_str}

【各キャラクターの現在の状態と交友関係】
{agent_status_text}

【🚨 超重要：自律的な人間関係（ドラマ）の構築ルール】
あなたは各エージェントの行動をシミュレーションする際、同じ街にいる他のエージェントと偶然出会ったり、連絡を取ったりして「関係性が変化・発展」するドラマを自律的に発生させても構いません。
・初めて出会って連絡先を交換した
・一緒に出かけて親友になった
・価値観が合わず大喧嘩した（絶縁）
・恋人に発展した
このような「関係性の変化」が起きた場合のみ、JSONの `relationship_updates` 配列にその結果を出力してください。

【継続イベント（Ongoing Event）の自律予約ルール】
もし今回の行動で、日常のスケジュールから逸脱した「数時間にわたるイベント」が新しく始まった場合、そのイベントが何時間（何ターン）続くかを自律的に決定して予約してください。（※1ターン＝30分）

必ず以下のJSONフォーマットのみを出力してください。
{{
  "events": [
    {{
      "agent_id": "エージェントのID",
      "event_description": "この30分間の具体的な情景描写",
      "new_status": {{ "mood": 数値, "social": 数値, "libido": 数値 }},
      "action_flag": "NORMAL や INTIMATE_EVENT など",
      "ongoing_event_trigger": {{
        "type": "SHOPPING_OR_TRIP_ETC",
        "name": "イベント名",
        "turns": 予約するターン数(整数)
      }},
      "relationship_updates": [
        {{
          "target_id": "関係が変化した相手のID",
          "type": "関係性（例：親友、飲み友達、恋人、絶縁など）",
          "origin": "きっかけ",
          "notes": "特記事項（相手への現在の感情など）"
        }}
      ] // ※関係性に変化がない場合は空配列 [] にすること
    }}
  ]
}}
"""

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json", "temperature": 0.8},
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
    # 💾 4. 解析と「相関図・予約ターン」のセーブ処理
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
            rel_updates = event.get("relationship_updates", [])

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
                    is_user_event = agent_data.get("is_user_event", False)

                    # ユーザーイベント中ならAIの上書き予約をブロック
                    if is_user_event:
                        trigger = None 
                        
                    if trigger and trigger.get("turns", 0) > 0:
                        print(f"🎉 [NEW_EVENT] {a_id} が「{trigger.get('name')}」を {trigger.get('turns')} ターン予約しました！")
                        update_data["ongoing_event"] = {
                            "type": trigger.get("type", "CUSTOM"),
                            "name": trigger.get("name", "特殊イベント"),
                            "remaining_turns": max(0, trigger.get("turns") - 1)
                        }
                    elif current_ongoing and current_ongoing.get("remaining_turns", 0) > 0:
                        remaining = current_ongoing["remaining_turns"] - 1
                        if remaining > 0:
                            current_ongoing["remaining_turns"] = remaining
                            update_data["ongoing_event"] = current_ongoing
                            print(f"⏳ [ONGOING] {a_id} の「{current_ongoing.get('name')}」継続中（残り {remaining} ターン）")
                        else:
                            update_data["ongoing_event"] = firestore.DELETE_FIELD
                            print(f"🏁 [FINISHED] {a_id} の「{current_ongoing.get('name')}」が終了し、日常に戻りました！")
                    else:
                        update_data["ongoing_event"] = firestore.DELETE_FIELD

                    # 🌟🌟 相関図（人間ドラマ）の自動双方向セーブ処理！ 🌟🌟
                    if rel_updates:
                        current_rels = raw_data.get("relationships", {})
                        
                        for rel in rel_updates:
                            t_id = rel.get("target_id")
                            # 相手が存在するかチェック
                            target_ref = db.collection("agents").document(t_id)
                            target_doc = target_ref.get()
                            
                            if target_doc.exists:
                                # 自分自身の更新
                                current_rels[t_id] = {
                                    "type": rel.get("type"),
                                    "origin": rel.get("origin"),
                                    "notes": rel.get("notes")
                                }
                                update_data["relationships"] = current_rels
                                
                                # 相手の更新（双方向リンク）
                                target_data = target_doc.to_dict()
                                target_rels = target_data.get("relationships", {})
                                target_rels[a_id] = {
                                    "type": rel.get("type"),
                                    "origin": rel.get("origin"),
                                    "notes": f"{a_id} 視点: " + rel.get("notes")
                                }
                                target_ref.update({"relationships": target_rels})
                                print(f"💞 [RELATION_DRAMA] {a_id} と {t_id} の関係が「{rel.get('type')}」に更新されました！")

                    # 自身のデータを上書き保存
                    doc_ref.update(update_data)
                    
                    print("-" * 50)
                    print(f"📖 {desc}")

        print("✨ [SUCCESS] シミュレーション完了！ターン管理と人間関係がFirestoreに保存されました！")

    except Exception as e:
        print(f"❌ 解析失敗: {e}")
        print("生のレスポンス:", response.text)

if __name__ == "__main__":
    generate_world_events()
