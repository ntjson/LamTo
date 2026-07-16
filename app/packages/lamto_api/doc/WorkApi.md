# lamto_api.api.WorkApi

## Load the API package
```dart
import 'package:lamto_api/api.dart';
```

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workRatingCreate**](WorkApi.md#workratingcreate) | **POST** /api/v1/work/{id}/rating | 


# **workRatingCreate**
> WorkRatingResult workRatingCreate(id, workRatingRequest)



### Example
```dart
import 'package:lamto_api/api.dart';
// TODO Configure API key authorization: knoxApiToken
//defaultApiClient.getAuthentication<ApiKeyAuth>('knoxApiToken').apiKey = 'YOUR_API_KEY';
// uncomment below to setup prefix (e.g. Bearer) for API key, if needed
//defaultApiClient.getAuthentication<ApiKeyAuth>('knoxApiToken').apiKeyPrefix = 'Bearer';

final api = LamtoApi().getWorkApi();
final int id = 56; // int | 
final WorkRatingRequest workRatingRequest = ; // WorkRatingRequest | 

try {
    final response = api.workRatingCreate(id, workRatingRequest);
    print(response);
} catch on DioException (e) {
    print('Exception when calling WorkApi->workRatingCreate: $e\n');
}
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id** | **int**|  | 
 **workRatingRequest** | [**WorkRatingRequest**](WorkRatingRequest.md)|  | 

### Return type

[**WorkRatingResult**](WorkRatingResult.md)

### Authorization

[knoxApiToken](../README.md#knoxApiToken)

### HTTP request headers

 - **Content-Type**: application/json, application/x-www-form-urlencoded, multipart/form-data
 - **Accept**: application/json, application/problem+json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

