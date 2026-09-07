# Doma Skills

[English](README.md) | 日本語

Java および Kotlin 向けのコンパイル時データベースアクセスフレームワーク Doma を使う開発者のための、インストール可能な [Agent Skills](https://agentskills.io/) 集です。

## 利用可能なスキル

### `doma-setup-project`

次のような場合にこのスキルを使用します。

- 素の Java Gradle プロジェクトに Doma とアノテーション処理を追加する
- 素の Java Maven プロジェクトを設定し、最初のコンパイル可能な DAO を作成する
- 初回ビルドで DAO 実装が生成されなかった原因を診断する

このスキルは、Java 17 以降のビルド設定、`doma-core` と `doma-processor` のバージョン整合、最初の `Config`・エンティティ・DAO・SQL リソース、クリーンなコンパイル、生成ソースの再帰的な確認、セットアップの診断を扱います。

Spring Boot、Quarkus、その他のフレームワーク統合、KAPT や KSP を用いた Kotlin、高度な DAO および 2-way SQL 設計、Criteria API、トランザクション、データベースマイグレーションは対象外です。

### `doma-setup-kotlin-project`

次のような場合にこのスキルを使用します。

- 素の Kotlin/JVM Gradle Kotlin DSL プロジェクトに Doma と KAPT を追加する
- アノテーション処理が動作していることを確認する最初の Kotlin DAO を作成する
- KAPT が DAO 実装を生成しなかった原因を診断する

このスキルは、JDK 17 以降のセットアップ、`doma-kotlin` と `doma-processor` のバージョン整合、インライン SQL を持つトップレベル DAO による動作確認、クリーンな Gradle ビルド、生成ソースの再帰的な確認、初期セットアップの診断を扱います。

Maven、Java のみのセットアップ、Spring Boot、Quarkus、その他のフレームワーク統合、KSP の設定、外部 SQL リソース、エンティティ・ドメイン・埋め込みクラスの設計、Criteria API および KQueryDsl、トランザクション、マイグレーション、広範なデータベース方言のガイダンスは対象外です。

### `doma-connect-aws-rds`

既存の素の Java または Kotlin の Doma アプリケーションを、既存の Amazon RDS PostgreSQL、Aurora PostgreSQL、RDS MySQL、Aurora MySQL に接続する、または接続の不具合を修復する場合にこのスキルを使用します。

Direct JDBC、IAM データベース認証、Secrets Manager 連携、既存の RDS Proxy 経由の接続、AWS Advanced JDBC Wrapper、Doma の方言と `DataSource` の選択、段階的な接続検証、対象を絞った読み取り専用の AWS 調査を扱います。

AWS の調査は読み取り専用で、シークレットの値を取得したり出力したりすることはありません。クラウドリソースのプロビジョニングや変更も行いません。フレームワークの配線とトランザクション、デプロイ、スキーマのマイグレーション、エンティティや業務 DAO の設計、スロークエリやインデックスのチューニングは対象外です。

### `doma-sync-entities-from-database`

既存の Doma Gradle プロジェクトで、Doma CodeGen を設定し、選択した PostgreSQL または MySQL のテーブルから Java または Kotlin のエンティティ候補を生成し、既存エンティティと構造的に比較して、手書きコードを上書きすることなくデータベースを正とする確実な変更だけを適用する場合にこのスキルを使用します。

Gradle の Kotlin DSL と Groovy DSL のプロジェクト、ローカルまたは Docker 上のデータベース、RDS および Aurora のインスタンスまたはクラスター、RDS Proxy に対応しています。認証情報を含まない JDBC メタデータのスナップショットと一時的な候補を `build/doma-codegen` 配下に作成し、`SAFE` な編集を個別に適用し、`REVIEW_REQUIRED` の提案は 1 件ずつ正確な内容に対する明示的な承認を必要とします。ドメイン、独自アノテーション、メソッド、関連、継承、解釈が曖昧なソース形状は、安全側に倒して処理を中断します。

ローカルの認証情報は `DOMA_CODEGEN_DB_URL`、`DOMA_CODEGEN_DB_USER`、`DOMA_CODEGEN_DB_PASSWORD` から取得し、無い場合はユーザーホームの対応する Gradle プロパティにフォールバックします。プロジェクト内に置かれた秘密情報は拒否します。AWS への接続では、アカウント・リージョン・接続先を正確に確認したうえで、Secrets Manager または都度発行の IAM データベース認証トークンを使用します。認証情報は隔離された子プロセスにのみ渡され、出力からは伏字化され、生成物には一切保存されません。

Maven、スキーマやマイグレーションの変更、DAO や 2-way SQL の生成、クエリチューニング、AWS リソースのプロビジョニング、リネームの推測、エンティティの削除、未承認のプロパティ削除は対象外です。

## インストール

```bash
npx skills add momosetkn/doma-skills --list
npx skills add momosetkn/doma-skills
npx skills add momosetkn/doma-skills --skill doma-setup-project
npx skills add momosetkn/doma-skills --skill doma-setup-kotlin-project
npx skills add momosetkn/doma-skills --skill doma-connect-aws-rds
npx skills add momosetkn/doma-skills --skill doma-sync-entities-from-database
```

## 使い方

```text
Use $doma-setup-project to add Doma to this plain Java Gradle project and verify annotation processing.
```

```text
Use $doma-setup-project to diagnose why this Maven build creates no generated DAO implementation.
```

```text
Use $doma-setup-kotlin-project to add Doma and KAPT to this Kotlin/JVM Gradle project and verify DAO generation.
```

```text
Use $doma-connect-aws-rds to inspect the existing Aurora PostgreSQL target in ap-northeast-1 and connect this Kotlin Doma Lambda through its existing RDS Proxy with IAM authentication.
```

```text
Use $doma-sync-entities-from-database to connect to my local PostgreSQL database, generate Doma entities for the tenant tables, and merge only safe changes.
```

```text
Use $doma-sync-entities-from-database to compare our Kotlin entities with an Aurora MySQL schema through RDS Proxy without overwriting handwritten code.
```

## 対象とする Doma のバージョン

各スキルのガイダンスは、同梱の `3.14.1-SNAPSHOT` のソースを基準に調査し、該当する場合はリリース済みの Doma `3.14.0` のドキュメントや例を参照しています。エンティティ同期は、検証済みの Doma CodeGen Plugin `3.2.2` を基準としつつ、対象プロジェクトが既に選択している互換バージョンがあればそれを維持します。これらの基準は、いずれかのバージョンが現時点の最新安定版であると主張するものではありません。