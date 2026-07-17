# lamto_api.model.LedgerEntryDetail

## Load the model package
```dart
import 'package:lamto_api/api.dart';
```

## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **int** |  | 
**contractorName** | **String** |  | 
**actualCostVnd** | **int** |  | 
**publishedAt** | [**DateTime**](DateTime.md) |  | 
**proposedAmountVnd** | **int** |  | 
**integrityStatus** | **String** |  | 
**whatWasFixed** | **String** | Resident-visible narrative of work completed. | 
**why** | **String** | Resident-visible rationale (cause / purpose / emergency reason). | 
**approvers** | [**BuiltList&lt;LedgerApprover&gt;**](LedgerApprover.md) |  | 
**payload** | [**JsonObject**](.md) |  | 
**verification** | [**Verification**](Verification.md) |  | 
**redactedDocuments** | [**BuiltList&lt;RedactedDocument&gt;**](RedactedDocument.md) |  | 
**corrections** | [**BuiltList&lt;Correction&gt;**](Correction.md) |  | 
**proof** | [**Proof**](Proof.md) |  | 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


