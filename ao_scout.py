#!/usr/bin/env python3
"""
🔍 AO Scout — Version Avec Notion Cache
Scrape BOAMP → Check doublon en Notion → Create + Discord (si nouveau)

WORKFLOW:
1. Query BOAMP API (3 champs: titre, catégories, description)
2. Pour chaque AO:
   - is_duplicate(idweb) → check Notion AO Scout
   - Si OUI → skip (déjà vu)
   - Si NON → create_ao() + send_discord_alert()
3. Report Discord (stats)

Configuration:
- NOTION_API_KEY (required)
- NOTION_AO_SCOUT_DATA_SOURCE_ID (required)
- Discord webhook: DISCORD_AO_SCOUT_WEBHOOK (required)
- BOAMP: public API (no auth)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
import sys

# Import Notion helper
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from notion_ao_scout_simple import AOScoutNotionClient
except ImportError:
    logging.error("❌ notion_ao_scout_simple.py not found")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('ao_scout')

class AOScout:
    """Agent AO Scout avec cache Notion."""
    
    BOAMP_API_URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1"
    
    DISCORD_WEBHOOK = os.getenv(
        "DISCORD_AO_SCOUT_WEBHOOK",
        "https://discord.com/api/webhooks/1488230004004229240/VIgIsx5Z81LHVHLZaMjqwXoD71vU2bIqzWf5fWMS3C3mTWCtUv5a-gXlNS2WRzk4izmM"
    )
    
    # Keywords — Clos & Couvert uniquement
    PRIORITY_KEYWORDS_5PT = [
        "étanchéité", "couverture", "façade", "bardage", "ravalement"
    ]
    ETANCHEITE_KEYWORDS_4PT = [
        "étanchéité toiture", "étanchéité terrasse", "membrane étanche",
        "imperméabilisation", "SEL", "réfection étanchéité",
        "étanchéité bitumineuse", "étanchéité PVC", "étanchéité EPDM"
    ]
    COUVERTURE_KEYWORDS_4PT = [
        "toiture", "réfection toiture"
    ]
    FACADE_KEYWORDS_4PT = [
        "ravalement façade", "enduit façade", "ITE", "rénovation façade",
        "nettoyage façade"
    ]
    BARDAGE_KEYWORDS_4PT = [
        "bardage bois", "bardage métallique", "bardage façade", "pose bardage"
    ]
    
    KEYWORDS = (
        PRIORITY_KEYWORDS_5PT +
        ETANCHEITE_KEYWORDS_4PT +
        COUVERTURE_KEYWORDS_4PT +
        FACADE_KEYWORDS_4PT +
        BARDAGE_KEYWORDS_4PT
    )
    
    # 33 départements couverts
    DEPTS = {
        # Île-de-France (8)
        "75", "92", "93", "94", "77", "78", "91", "95",
        # Périphérie IDF (5)
        "60", "28", "45", "89", "27",
        # Lyon + périphérie (4)
        "69", "01", "38", "42",
        # Lille + périphérie (2)
        "59", "62",
        # Basse-Normandie (3)
        "14", "50", "61",
        # Haute-Normandie (1)
        "76",
        # Bretagne (4)
        "35", "22", "56", "29",
        # Pays de la Loire (5)
        "44", "49", "72", "53", "85",
        # Centre-Val de Loire (3)
        "37", "41", "36"
    }
    
    MIN_DAYS = 3  # Deadline minimum en jours
    
    def __init__(self):
        self.notion = AOScoutNotionClient()
        self.stats = {
            "total_found": 0,
            "new_aos": 0,
            "duplicates": 0,
            "errors": 0
        }
    
    def calculate_score(self, ao: Dict) -> tuple:
        """
        Calcule le score d'un AO et détermine le niveau d'urgence.
        
        Critères:
        - Deadline (0-4 pts): ≥14j=4, ≥7j=3, ≥5j=2, ≥3j=1
        - Keywords prioritaires (5 pts): étanchéité, couverture, façade, bardage, ravalement
        - Étanchéité variantes (4 pts): 9 termes
        - Couverture (4 pts): 2 termes
        - Façade (4 pts): 5 termes
        - Bardage (4 pts): 4 termes
        - Localisation (0-3 pts)
        - Multi-lots bonus (0-2 pts)
        """
        score = 0
        titre = ao.get("titre", "").lower()
        deadline_days = ao.get("deadline_days", 0)
        dept = ao.get("dept", "")
        
        # 1. Deadline (0-4 points)
        if deadline_days >= 14:
            score += 4
        elif deadline_days >= 7:
            score += 3
        elif deadline_days >= 5:
            score += 2
        elif deadline_days >= 3:
            score += 1
        
        # 2. Keywords par catégorie
        for kw in self.PRIORITY_KEYWORDS_5PT:
            if kw in titre:
                score += 5
                break
        if any(kw in titre for kw in self.ETANCHEITE_KEYWORDS_4PT):
            score += 4
        if any(kw in titre for kw in self.COUVERTURE_KEYWORDS_4PT):
            score += 4
        if any(kw in titre for kw in self.FACADE_KEYWORDS_4PT):
            score += 4
        if any(kw in titre for kw in self.BARDAGE_KEYWORDS_4PT):
            score += 4
        
        # 3. Localisation (0-3 points)
        if dept in ["75", "92", "93", "94"]:
            score += 3
        elif dept in ["77", "78", "91", "95"]:
            score += 2
        elif dept in ["69", "59"]:
            score += 3
        elif dept in ["60", "28", "45", "89", "27"]:
            score += 2
        elif dept in ["01", "38", "42", "62"]:
            score += 2
        elif dept in ["14", "50", "61"]:
            score += 2
        elif dept in ["76"]:
            score += 2
        elif dept in ["35", "44"]:
            score += 2
        elif dept in ["22", "56", "29", "49", "72", "53", "85"]:
            score += 1
        elif dept in ["37", "41", "36"]:
            score += 1
        
        # 4. Multi-lots bonus (0-2 points)
        categories_present = sum([
            any(kw in titre for kw in self.PRIORITY_KEYWORDS_5PT),
            any(kw in titre for kw in self.ETANCHEITE_KEYWORDS_4PT),
            any(kw in titre for kw in self.COUVERTURE_KEYWORDS_4PT),
            any(kw in titre for kw in self.FACADE_KEYWORDS_4PT),
            any(kw in titre for kw in self.BARDAGE_KEYWORDS_4PT),
        ])
        if categories_present >= 3:
            score += 2
        elif categories_present >= 2:
            score += 1
        
        # Niveau d'urgence
        if score >= 15:
            urgence = "🔥 ULTRA-PRIORITAIRE"
        elif score >= 12:
            urgence = "⭐ PRIORITAIRE"
        elif score >= 8:
            urgence = "📋 INTÉRESSANT"
        elif score >= 5:
            urgence = "📂 À CONSULTER"
        else:
            urgence = "📌 ARCHIVÉ"
        
        return score, urgence
    
    def query_boamp(self) -> List[Dict]:
        """Query BOAMP API via 3 champs: titre, catégories, description."""
        try:
            logger.info("🔍 Querying BOAMP API (multi-champs)...")
            
            all_records = []
            seen_idwebs = set()
            
            params_base = {
                "limit": 100,
                "offset": 0,
                "order_by": "datelimitereponse DESC"
            }
            
            for i, field in enumerate(["objet", "descripteur_libelle", "donnees"], 1):
                labels = {
                    "objet": "TITRE",
                    "descripteur_libelle": "CATÉGORIES",
                    "donnees": "DESCRIPTION"
                }
                logger.info(f"  📋 Query {i}: Recherche dans {labels[field]}...")
                
                params = {**params_base, "where": self._build_boamp_filter(field)}
                response = requests.get(
                    self.BOAMP_API_URL + "/catalog/datasets/boamp/records",
                    params=params,
                    timeout=15
                )
                
                if response.status_code == 200:
                    records = response.json().get("results", [])
                    new_count = 0
                    for rec in records:
                        idweb = rec.get("idweb")
                        if idweb and idweb not in seen_idwebs:
                            all_records.append(rec)
                            seen_idwebs.add(idweb)
                            new_count += 1
                    logger.info(f"     ✅ Trouvés: {len(records)} (dont {new_count} nouveaux)")
                else:
                    logger.error(f"❌ Query {i} error: {response.status_code}")
            
            logger.info(f"✅ TOTAL FUSIONNÉ: {len(all_records)} AOs uniques")
            return all_records
        
        except Exception as e:
            logger.error(f"❌ BOAMP query error: {e}")
            return []
    
    def _build_boamp_filter(self, search_field="objet") -> str:
        """Construit le WHERE clause pour l'API BOAMP."""
        keyword_filters = [f'{search_field} like "%{kw}%"' for kw in self.KEYWORDS]
        dept_filters = [f'code_departement like "%{dept}%"' for dept in self.DEPTS]
        deadline_min = (datetime.now() + timedelta(days=self.MIN_DAYS)).isoformat()
        
        return (
            "(" + " OR ".join(keyword_filters) + ")"
            + " AND (" + " OR ".join(dept_filters) + ")"
            + f' AND datelimitereponse >= "{deadline_min}"'
        )
    
    def parse_ao(self, boamp_record: Dict) -> Optional[Dict]:
        """Parse un record BOAMP en AO data."""
        try:
            idweb = boamp_record.get("idweb", "")
            titre = boamp_record.get("objet", "")
            client = boamp_record.get("nomacheteur", "")
            
            depts = boamp_record.get("code_departement", [])
            localisation = ", ".join([f"({d})" for d in depts]) if isinstance(depts, list) else f"({depts})"
            
            deadline_str = boamp_record.get("datelimitereponse", "")
            deadline = deadline_str[:10] if deadline_str else ""
            deadline_days = self._calculate_deadline_days(deadline_str)
            
            dept = depts[0] if isinstance(depts, list) and depts else ""
            lots = self._detect_lots(titre)
            
            lien_boamp = boamp_record.get("url_avis", "")
            if not lien_boamp and idweb:
                lien_boamp = f"https://www.boamp.fr/pages/avis/?q=idweb:{idweb}"
            
            score, urgence = self.calculate_score({
                "titre": titre,
                "deadline_days": deadline_days,
                "dept": dept
            })
            
            donnees = self._parse_donnees(boamp_record)
            lieu_execution = self._extract_lieu_execution(donnees)
            details = self._extract_details(donnees)
            
            return {
                "idweb": idweb,
                "titre": titre[:500],
                "client": client[:200],
                "localisation": localisation[:100],
                "deadline": deadline,
                "deadline_days": deadline_days,
                "dept": dept,
                "score": score,
                "urgence": urgence,
                "lots": lots,
                "lien_boamp": lien_boamp,
                "date_detection": datetime.now().isoformat()[:10],
                "lieu_execution": lieu_execution,
                "details": details,
                "notes": ""
            }
        
        except Exception as e:
            logger.error(f"❌ Parse error: {e}")
            return None
    
    def _parse_donnees(self, boamp_record: Dict) -> dict:
        """Parse le champ 'donnees' BOAMP en dict Python."""
        try:
            donnees_raw = boamp_record.get("donnees", "{}")
            if not donnees_raw:
                return {}
            return json.loads(donnees_raw) if isinstance(donnees_raw, str) else donnees_raw
        except:
            return {}

    def _find_field(self, d, keys, depth=0):
        """Recherche récursive d'un champ dans un dict imbriqué."""
        if depth > 6: return ""
        if isinstance(d, dict):
            for k, v in d.items():
                if k.upper() in keys and isinstance(v, str) and len(v) > 10:
                    return v
                result = self._find_field(v, keys, depth+1)
                if result:
                    return result
        elif isinstance(d, list):
            for item in d[:3]:
                result = self._find_field(item, keys, depth+1)
                if result:
                    return result
        return ""

    def _extract_lieu_execution(self, donnees: dict) -> str:
        """Extrait le lieu d'exécution depuis donnees BOAMP."""
        try:
            # Format ancien: donnees.lieuExecution
            lieu = self._find_field(donnees, {"LIEUEXECUTION"})
            if not lieu:
                # Format nouveau: donnees.OBJET.LIEU_EXEC_LIVR
                lieu_obj = donnees.get("OBJET", {}).get("LIEU_EXEC_LIVR", {})
                if isinstance(lieu_obj, dict):
                    parts = [lieu_obj.get("ADRESSE", ""), lieu_obj.get("CP", ""), lieu_obj.get("VILLE", "")]
                    lieu = " ".join(p for p in parts if p)
            return lieu[:500] if lieu else ""
        except Exception as e:
            logger.debug(f"Lieu extraction failed: {e}")
            return ""

    def _extract_details(self, donnees: dict) -> str:
        """Extrait les renseignements complémentaires depuis donnees BOAMP."""
        try:
            # Format ancien: donnees.RENSEIGNEMENTS_COMPLEMENTAIRES.RENS_COMPLEMENT
            details = self._find_field(donnees, {"RENS_COMPLEMENT"})
            if not details:
                # Format nouveau: donnees.autresInformComplementaire
                details = self._find_field(donnees, {"AUTRESINFORMCOMPLEMENTAIRE"})
            return details[:2000] if details else ""
        except Exception as e:
            logger.debug(f"Details extraction failed: {e}")
            return ""

    def _calculate_deadline_days(self, deadline_str: str) -> int:
        """Calcule le nombre de jours restants avant la deadline."""
        try:
            if not deadline_str:
                return 0
            deadline = datetime.fromisoformat(deadline_str[:10])
            return max(0, (deadline - datetime.now()).days)
        except:
            return 0
    
    def _detect_lots(self, titre: str) -> List[str]:
        """Détecte les lots clos & couvert dans le titre."""
        lots = []
        t = titre.lower()
        
        if any(kw in t for kw in ["étanchéité", "étanché"]):
            lots.append("Étanchéité")
        if any(kw in t for kw in ["façade", "ravalement"]):
            lots.append("Façade")
        if any(kw in t for kw in ["couverture", "toiture"]):
            lots.append("Couverture")
        if any(kw in t for kw in ["bardage"]):
            lots.append("Bardage")
        if any(kw in t for kw in ["construction", "maçonnerie", "béton"]):
            lots.append("Construction")
        
        return lots if lots else ["Autres"]
    
    def _lot_emoji(self, lot: str) -> str:
        emojis = {
            "Étanchéité": "🏗️", "Façade": "🎨", "Couverture": "🔨",
            "Bardage": "📦", "Construction": "🧱", "Autres": "⚙️"
        }
        return emojis.get(lot, "•")
    
    def process_aos(self, boamp_records: List[Dict]) -> None:
        """Traite chaque AO: check doublon → create + Discord."""
        for record in boamp_records:
            try:
                self.stats["total_found"] += 1
                ao_data = self.parse_ao(record)
                if not ao_data or not ao_data.get("idweb"):
                    self.stats["errors"] += 1
                    continue
                
                idweb = ao_data["idweb"]
                if self.notion.is_duplicate(idweb):
                    self.stats["duplicates"] += 1
                    logger.info(f"🔄 SKIP (doublon): {idweb}")
                    continue
                
                page_id = self.notion.create_ao(ao_data)
                if page_id:
                    self.stats["new_aos"] += 1
                    self._send_discord_alert(ao_data)
                    logger.info(f"✅ NEW AO created: {idweb}")
                else:
                    self.stats["errors"] += 1
                    logger.error(f"❌ Failed to create: {idweb}")
            
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(f"❌ Process error: {e}")
    
    def _send_discord_alert(self, ao_data: Dict) -> bool:
        """Envoie une alerte Discord pour une nouvelle AO."""
        if not self.DISCORD_WEBHOOK:
            return False
        
        try:
            score = ao_data.get("score", 0)
            urgence = ao_data["urgence"]
            deadline_days = ao_data.get("deadline_days", 0)
            
            if score >= 12:
                lots_str = ", ".join([f"{self._lot_emoji(lot)} {lot}" for lot in ao_data["lots"]])
                deadline_str = f"{deadline_days}j" if deadline_days > 0 else "PASSÉ"
                if deadline_days < 3:
                    deadline_str = f"⚠️ {deadline_str} (URGENT)"
                content = f"""{urgence} **(score {score}/20)**

**{ao_data['titre'][:150]}**

🏢 **Client:** {ao_data['client'][:80]}
📍 **Localisation:** {ao_data['localisation']}
📅 **Deadline:** {deadline_str}
📋 **Lots:** {lots_str}

🔗 [Voir sur BOAMP]({ao_data['lien_boamp']})
━━━━━━━━━━━━━━━━━━━━━━━━
ID: `{ao_data['idweb']}`"""
            
            elif score >= 5:
                content = f"""{urgence} (score {score}/20)

**{ao_data['titre'][:120]}**

📅 {deadline_days}j | 📍 {ao_data['localisation']}
🔗 [BOAMP]({ao_data['lien_boamp']}) | ID: `{ao_data['idweb']}`"""
            
            else:
                content = f"{urgence} (score {score}/20): {ao_data['titre'][:80]} - [BOAMP]({ao_data['lien_boamp']}) | ID: `{ao_data['idweb']}`"
            
            response = requests.post(self.DISCORD_WEBHOOK, json={"content": content}, timeout=10)
            if response.status_code == 204:
                logger.info(f"✅ Discord alert sent: {ao_data['idweb']}")
                return True
            else:
                logger.error(f"❌ Discord error: {response.status_code}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Discord send error: {e}")
            return False
    
    def report_stats(self) -> None:
        """Envoie un rapport Discord avec les stats."""
        if not self.DISCORD_WEBHOOK:
            return
        try:
            content = f"""🔍 **AO Scout Session Report**

📊 Total trouvées: {self.stats['total_found']}
✅ Nouvelles: {self.stats['new_aos']}
🔄 Doublons: {self.stats['duplicates']}
❌ Erreurs: {self.stats['errors']}

⏱️ {datetime.now().strftime('%d/%m/%Y %H:%M')}"""
            requests.post(self.DISCORD_WEBHOOK, json={"content": content}, timeout=10)
        except Exception as e:
            logger.error(f"Report error: {e}")
    
    def run(self) -> None:
        """Lance l'agent complet."""
        logger.info("🚀 AO Scout Starting...")
        boamp_records = self.query_boamp()
        if not boamp_records:
            logger.warning("⚠️  No AOs found on BOAMP")
            return
        self.process_aos(boamp_records)
        self.report_stats()
        logger.info("✅ AO Scout Done")


if __name__ == "__main__":
    scout = AOScout()
    scout.run()
