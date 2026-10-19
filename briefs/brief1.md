HorRAGor BOT - Partie 1


Introduction & Objectifs
L'objectif de ce projet est de concevoir HorRAGor (ou GorRAGor), un agent conversationnel spécialisé dans l'univers de l'horreur (cinéma, littérature, jeux vidéo). Pour que cet agent soit pertinent et évite les hallucinations, il doit s'appuyer sur une base de connaissances hybride, riche et parfaitement structurée.
Dans cette première partie, vous devez valider les compétences du Bloc E1 en développant un pipeline d'ingestion capable de collecter, nettoyer et fusionner des données provenant de 5 sources hétérogènes. Ce socle de données servira de base à la future architecture RAG (Retrieval-Augmented Generation) du bot.


SOMMAIRE
 
Introduction & Objectifs	1
Ingestion Multimodale et Pipeline de Données Massives	3
Sources des Données (Acquisition Parallèle)	3
Stratégie de Fusion et Réconciliation (MDM)	4
Filtrage et Spécifications Techniques	4
Homogénéiser les formats de données pour assurer la cohérence.	4
Normalisation des dates :	4
Normalisation des scores :	5
Normalisation des textes :	5


Ingestion Multimodale et Pipeline de Données Massives

Sources des Données (Acquisition Parallèle)
Vous devez automatiser l'extraction des données depuis les canaux suivants :
Web Scraping (Selenium) : Extraction dynamique Rotten Tomatoes pour capter les tendances et avis récents (tomatometer_score, audience_score, critics_consensus).
API Externe : Interrogation de l'API TMDB (The Movie Database) pour récupérer les métadonnées structurées (title, overview, release_date, vote_average, popularity, poster_path).
Fichiers Locaux (Polars) : Lecture et traitement rapide de datasets Kaggle (format CSV) sur les classiques de la littérature d'épouvante (métadonnées complètes incluant budget, revenue).
Bibliothèque : Polars (alternative performante à Pandas pour les gros volumes)
Nettoyage : suppression des doublons sur title + release_date


Base de Données (SQLite) : Extraction depuis une base relationnelle existante (tconst (ID IMDB), primaryTitle, averageRating, numVotes).
Requête d’extraction : jointure title_basics ↔ title_ratings filtrée sur le genre Horror
Seuil qualité : numVotes >= 1000 pour exclure les films obscurs


Système Big Data (PySpark) : Traitement d'un volume massif de données des fichiers Kaggle splittés. Depuis IMDB. 

Stratégie de Fusion et Réconciliation (MDM)
La fusion des sources ne doit pas être une simple accumulation, mais une consolidation intelligente suivant une logique de priorité décroissante :
Source Maîtresse : TMDB (Identifiants de référence et titres officiels).
Enrichissement 1 : Rotten Tomatoes (Scores et critiques).
Enrichissement 2 : Kaggle (Détails littéraires et synopsis).
Enrichissement 3 : IMDB (Casting et trivia).
Enrichissement 4 : Spark Data (Analyses textuelles lourdes).
Méthodes de matching (Réconciliation) :
Niveau 1 : Correspondance exacte sur tmdb_id.
Niveau 2 : Correspondance exacte sur imdb_id.
Niveau 3 (Fuzzy Matching) : En l'absence d'ID, correspondance sur le couple [Titre + Année] via un algorithme de similarité textuelle (ex: distance de Levenshtein).
Filtrage et Spécifications Techniques
Le pipeline doit garantir une donnée "Gold" prête pour le RAG :
Filtrage Thématique : Exclusion stricte de tout contenu hors-sujet (seul le genre Horreur/Gore doit subsister).
Normalisation : Conversion des formats (dates ISO 8601, durées en minutes) et nettoyage HTML/Markdown.
Dédoublonnement : Chaque entité doit être unique après fusion.
Gestion des manques : Si TMDB manque d'un synopsis, le système doit automatiquement basculer sur la source de priorité suivante.
Homogénéiser les formats de données pour assurer la cohérence.
Normalisation des dates :
Les sources utilisent des formats hétérogènes : TMDB (YYYY-MM-DD), Kaggle (YYYY-MM-DD ou YYYY seul), IMDB (startYear entier). L’agrégateur normalise toutes les dates au format ISO 8601. Pour les sources ne fournissant que l’année, la date est fixée au 1er janvier (YYYY-01-01).
Normalisation des scores :
TMDB et IMDB utilisent une échelle 0-10 (décimal), Rotten Tomatoes 0-100 (pourcentage). Les scores RT sont conservés en échelle native car ils représentent une métrique distincte (pourcentage de critiques positives vs note moyenne).
Normalisation des textes :
Suppression des espaces superflus (trim, normalisation whitespace), conversion en UTF-8, suppression des balises HTML résiduelles.
Modélisation et Persistance des Données (Supabase & SQLAlchemy)
Une fois l'étape d'agrégation et de nettoyage finalisée, vous devrez structurer la persistance de cette "Source de Vérité" au sein d'une architecture professionnelle. En vous appuyant sur la méthodologie Merise, vous concevrez une base de données relationnelle robuste intégrant les principes de la RGPD (minimisation des données et sécurité). 
Vous utiliserez SQLAlchemy ORM pour assurer l'interface entre votre code et le moteur de stockage. Ce travail devra impérativement s'accompagner d'une documentation technique complète incluant le MCD (Modèle Conceptuel de Données), le MLD (Modèle Logique de Données) et le MPD (Modèle Physique de Données). 
Enfin, pour garantir la disponibilité de vos données pour la future phase RAG, votre base de données sera déployée et hébergée sur Supabase.

