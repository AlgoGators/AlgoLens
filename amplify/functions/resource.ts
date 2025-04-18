import { defineFunction } from '@aws-amplify/backend';

export const appFunction = defineFunction({
  // this name becomes the CloudFormation logical ID
  name: 'backendApp',
  // path to your handler; relative to this file
  entry: '../../../backend/app.py',
  runtime: 'python3.9',
});
